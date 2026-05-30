from __future__ import annotations

from datetime import datetime
import json
import time
from types import SimpleNamespace

from sqlalchemy.orm import Session

from core.db.models import (
    Agent,
    AgentKnowledgeBase,
    AgentTool,
    AgentVersion,
    ModelConfig,
    Run,
    RunStep,
    Session as ChatSession,
    SessionMemory,
    Tool,
    UserModelConfig,
    Upload,
    WorkflowDefinition,
)
from core.integrations.llm import OpenAICompatibleProvider
from core.services.agents import get_agent_detail, normalize_memory, normalize_rag, normalize_tool_policy
from core.services.rag import retrieve
from core.services.memory import format_profile_memory, get_memory_profile, memory_used_event
from core.services.models import resolve_agent_model
from core.services.tools import execute_tool, tool_call_event, tool_schema_for_llm
from core.services.uploads import get_workspace_uploads
from core.services.user_models import (
    resolve_user_model_config,
    user_model_runtime_config,
)
from core.services import web_search as web_search_service
from core.services.web_search import WebSearchError


def default_workflow() -> list[dict]:
    return [
        {"id": "start", "type": "Start", "name": "接收用户输入", "config": {}},
        {"id": "knowledge", "type": "Knowledge", "name": "检索绑定知识库", "config": {"top_k": 4}},
        {"id": "tool", "type": "Tool", "name": "调用绑定工具", "config": {"tools": []}},
        {"id": "llm", "type": "LLM", "name": "生成候选回答", "config": {}},
        {"id": "answer", "type": "Answer", "name": "输出最终回答", "config": {}},
    ]


class WorkflowRunner:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.provider = OpenAICompatibleProvider()

    def run(
        self,
        *,
        agent: Agent,
        chat_session: ChatSession,
        user_message: str,
        mode: str = "draft",
        variables: dict | None = None,
        rag_enabled: bool | None = None,
        rag_options: dict | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        attachments: list[dict] | None = None,
    ) -> tuple[Run, str, list[dict], list[dict]]:
        runtime = self._runtime_agent(agent, mode, chat_session.user_id)
        upload_ids = [str(item.get("id")) for item in attachments or [] if item.get("id")]
        uploads = get_workspace_uploads(self.db, workspace_id=agent.workspace_id, upload_ids=upload_ids)
        self._validate_model_capabilities(runtime.capability_config, uploads)
        thinking_status = self._thinking_status(runtime.capability_config, thinking_enabled)
        search_status = self._search_status(user_message, search_enabled)

        rag_config = normalize_rag({**dict(runtime.settings.get("rag") or {}), **dict(rag_options or {})})
        effective_rag_enabled = rag_config["enabled_by_default"] if rag_enabled is None else bool(rag_enabled)

        run = Run(workspace_id=agent.workspace_id, agent_id=agent.id, session_id=chat_session.id, status="running")
        self.db.add(run)
        self.db.flush()
        self.db.commit()
        self.db.refresh(run)

        memory = self._session_memory(chat_session.id)
        profile_memory = get_memory_profile(
            self.db,
            workspace_id=agent.workspace_id,
            user_id=chat_session.user_id,
            agent_id=agent.id,
        )
        profile_memory_text = format_profile_memory(profile_memory)
        profile_memory_event = memory_used_event(profile_memory, session_summary_used=bool(memory and memory.summary))
        context: dict = {
            "input": user_message,
            "sources": [],
            "tool_outputs": [],
            "draft": "",
            "variables": self._merge_variables(runtime.settings.get("variables", []), variables or {}),
            "memory_summary": memory.summary if memory else "",
            "profile_memory": profile_memory_text,
            "profile_memory_used": profile_memory_event,
            "memory_enabled": normalize_memory(runtime.settings.get("memory")).get("enabled", False),
            "rag_enabled": effective_rag_enabled,
            **({"rag_enabled_request": rag_enabled} if rag_enabled is not None else {}),
            "rag_top_k": rag_config["top_k"],
            "rag_config": rag_config,
            "thinking_enabled": thinking_status["enabled"],
            "thinking_status": thinking_status,
            "search_enabled": search_status["enabled"],
            "search_status": search_status,
            "web_sources": search_status.get("sources", []),
            "uploads": uploads,
        }
        steps: list[dict] = []
        for node in runtime.workflow:
            output = self._execute_node(runtime, node, context)
            if not steps:
                output.setdefault("events", []).append({"event": "memory_used", "data": profile_memory_event})
                output.setdefault("events", []).append({"event": "thinking_status", "data": thinking_status})
                output.setdefault("events", []).append({"event": "search_status", "data": self._search_status_event(search_status)})
            events = output.pop("events", [])
            context.update(output)
            step = RunStep(
                run_id=run.id,
                node_id=node["id"],
                node_type=node["type"],
                status="succeeded",
                input={"input": user_message},
                output=output,
            )
            self.db.add(step)
            self.db.flush()
            self.db.commit()
            self.db.refresh(step)
            steps.append(
                {
                    "id": step.id,
                    "node_id": step.node_id,
                    "node_type": step.node_type,
                    "status": step.status,
                    "output": output,
                    "events": events,
                }
            )

        final_answer = context.get("answer") or context.get("draft") or "当前智能体没有生成回答。"
        if context.get("memory_enabled"):
            self._update_session_memory(
                chat_session.id,
                user_message,
                final_answer,
                int(runtime.settings.get("memory", {}).get("max_messages", 12)),
            )
        run.status = "succeeded"
        run.completed_at = datetime.utcnow()
        self.db.commit()
        return run, final_answer, [*context.get("sources", []), *context.get("web_sources", [])], steps

    def run_events(
        self,
        *,
        agent: Agent,
        chat_session: ChatSession,
        user_message: str,
        mode: str = "draft",
        variables: dict | None = None,
        rag_enabled: bool | None = None,
        rag_options: dict | None = None,
        thinking_enabled: bool | None = None,
        search_enabled: bool | None = None,
        attachments: list[dict] | None = None,
    ):
        runtime, run, context = self._start_run(
            agent=agent,
            chat_session=chat_session,
            user_message=user_message,
            mode=mode,
            variables=variables,
            rag_enabled=rag_enabled,
            rag_options=rag_options,
            thinking_enabled=thinking_enabled,
            search_enabled=search_enabled,
            attachments=attachments,
        )
        steps: list[dict] = []
        for node in runtime.workflow:
            if node["type"] == "LLM":
                output = yield from self._stream_llm_node(runtime, node, context)
            else:
                output = self._execute_node(runtime, node, context)
            if not steps:
                output.setdefault("events", []).append({"event": "memory_used", "data": context.get("profile_memory_used", {})})
                output.setdefault("events", []).append({"event": "thinking_status", "data": context.get("thinking_status", {})})
                output.setdefault("events", []).append({"event": "search_status", "data": self._search_status_event(context.get("search_status", {}))})
            events = output.pop("events", [])
            context.update(output)
            step = self._persist_step(run, node, user_message, output)
            step_payload = {
                "id": step.id,
                "node_id": step.node_id,
                "node_type": step.node_type,
                "status": step.status,
                "output": output,
                "events": events,
            }
            steps.append(step_payload)
            yield {"event": "step", "step": step_payload}

        final_answer = context.get("answer") or context.get("draft") or "当前智能体没有生成回答。"
        if context.get("memory_enabled"):
            self._update_session_memory(
                chat_session.id,
                user_message,
                final_answer,
                int(runtime.settings.get("memory", {}).get("max_messages", 12)),
            )
        run.status = "succeeded"
        run.completed_at = datetime.utcnow()
        self.db.commit()
        yield {
            "event": "complete",
            "run": run,
            "answer": final_answer,
            "sources": [*context.get("sources", []), *context.get("web_sources", [])],
            "steps": steps,
        }

    def _start_run(
        self,
        *,
        agent: Agent,
        chat_session: ChatSession,
        user_message: str,
        mode: str,
        variables: dict | None,
        rag_enabled: bool | None,
        rag_options: dict | None,
        thinking_enabled: bool | None,
        search_enabled: bool | None,
        attachments: list[dict] | None,
    ) -> tuple[object, Run, dict]:
        runtime = self._runtime_agent(agent, mode, chat_session.user_id)
        upload_ids = [str(item.get("id")) for item in attachments or [] if item.get("id")]
        uploads = get_workspace_uploads(self.db, workspace_id=agent.workspace_id, upload_ids=upload_ids)
        self._validate_model_capabilities(runtime.capability_config, uploads)
        thinking_status = self._thinking_status(runtime.capability_config, thinking_enabled)
        search_status = self._search_status(user_message, search_enabled)

        rag_config = normalize_rag({**dict(runtime.settings.get("rag") or {}), **dict(rag_options or {})})
        effective_rag_enabled = rag_config["enabled_by_default"] if rag_enabled is None else bool(rag_enabled)

        run = Run(workspace_id=agent.workspace_id, agent_id=agent.id, session_id=chat_session.id, status="running")
        self.db.add(run)
        self.db.flush()
        self.db.commit()
        self.db.refresh(run)

        memory = self._session_memory(chat_session.id)
        profile_memory = get_memory_profile(
            self.db,
            workspace_id=agent.workspace_id,
            user_id=chat_session.user_id,
            agent_id=agent.id,
        )
        profile_memory_text = format_profile_memory(profile_memory)
        profile_memory_event = memory_used_event(profile_memory, session_summary_used=bool(memory and memory.summary))
        context: dict = {
            "input": user_message,
            "sources": [],
            "tool_outputs": [],
            "draft": "",
            "variables": self._merge_variables(runtime.settings.get("variables", []), variables or {}),
            "memory_summary": memory.summary if memory else "",
            "profile_memory": profile_memory_text,
            "profile_memory_used": profile_memory_event,
            "memory_enabled": normalize_memory(runtime.settings.get("memory")).get("enabled", False),
            "rag_enabled": effective_rag_enabled,
            **({"rag_enabled_request": rag_enabled} if rag_enabled is not None else {}),
            "rag_top_k": rag_config["top_k"],
            "rag_config": rag_config,
            "thinking_enabled": thinking_status["enabled"],
            "thinking_status": thinking_status,
            "search_enabled": search_status["enabled"],
            "search_status": search_status,
            "web_sources": search_status.get("sources", []),
            "uploads": uploads,
        }
        return runtime, run, context

    def _persist_step(self, run: Run, node: dict, user_message: str, output: dict) -> RunStep:
        step = RunStep(
            run_id=run.id,
            node_id=node["id"],
            node_type=node["type"],
            status="succeeded",
            input={"input": user_message},
            output=output,
        )
        self.db.add(step)
        self.db.flush()
        self.db.commit()
        self.db.refresh(step)
        return step

    def _execute_node(self, agent, node: dict, context: dict) -> dict:
        node_type = node["type"]
        if node_type == "Start":
            return {
                "started": True,
                "variables": context.get("variables", {}),
                "rag_enabled": context.get("rag_enabled", True),
                "search_enabled": context.get("search_enabled", False),
                "attachment_count": len(context.get("uploads", [])),
            }
        if node_type == "Knowledge":
            effective_source = "request" if "rag_enabled_request" in context else "agent_default"
            if not context.get("rag_enabled", True):
                status = {
                    "enabled": False,
                    "effective_source": effective_source,
                    "knowledge_base_ids": [],
                    "query": context["input"],
                    "top_k": int(context.get("rag_top_k") or node.get("config", {}).get("top_k", 4)),
                    "matched_chunks": 0,
                    "sources_emitted": False,
                    "reason": "disabled",
                    "dense": {"matched": 0},
                    "bm25": {"matched": 0},
                    "rrf": {"matched": 0},
                    "rerank": {"enabled": False, "applied": False, "model": None, "error": None},
                    "cache": {"enabled": False, "hit": False, "backend": "none"},
                    "no_evidence": False,
                }
                return {"sources": [], "rag_enabled": False, "rag_status": status, "events": [{"event": "rag_status", "data": status}]}
            kb_ids = getattr(agent, "knowledge_base_ids", None)
            if kb_ids is None:
                kb_ids = [
                    row.knowledge_base_id
                    for row in self.db.query(AgentKnowledgeBase).filter(AgentKnowledgeBase.agent_id == agent.id).all()
                ]
            rag_result = retrieve(
                self.db,
                workspace_id=agent.workspace_id,
                knowledge_base_ids=kb_ids,
                query=context["input"],
                config=context.get("rag_config") or {},
                runtime_config=getattr(agent, "runtime_config", None),
            )
            sources = rag_result.sources
            status = {**rag_result.status, "effective_source": effective_source}
            return {"sources": sources, "rag_enabled": True, "rag_status": status, "events": [{"event": "rag_status", "data": status}]}
        if node_type == "Tool":
            bound_tools = self._runtime_tools(agent, node)
            tool_policy = (agent.settings.get("tool_policy") or {})
            allowed_names = set(tool_policy.get("allowed_tool_names") or [])
            if allowed_names:
                bound_tools = [t for t in bound_tools if t.name in allowed_names]
            if not bound_tools:
                return {"tool_outputs": [], "tool_stats": {"total_calls": 0, "tools_used": []}}

            tool_schemas = [tool_schema_for_llm(t) for t in bound_tools]
            messages = self._llm_messages(agent, context)
            total_calls = 0
            tools_used: list[str] = []
            events = []

            for _round in range(8):
                response = self.provider.chat(
                    messages,
                    model=agent.model,
                    temperature=agent.temperature,
                    runtime_config=agent.runtime_config,
                    tools=tool_schemas,
                )
                if response.content and not response.tool_calls:
                    return {
                        "draft": response.content,
                        "tool_outputs": [],
                        "tool_stats": {"total_calls": total_calls, "tools_used": tools_used},
                    }
                if response.tool_calls:
                    assistant_msg = {"role": "assistant", "content": response.content, "tool_calls": response.tool_calls}
                    messages.append(assistant_msg)
                    for tc in response.tool_calls:
                        func = tc["function"]
                        tool_name = func["name"]
                        try:
                            tool_args = json.loads(func.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            tool_args = {"input": func.get("arguments") or ""}
                        matching = next((t for t in bound_tools if t.name == tool_name), None)
                        started = time.monotonic()
                        if matching:
                            try:
                                result = execute_tool(matching, {"input": tool_args})
                                result["latency_ms"] = result.get("latency_ms", int((time.monotonic() - started) * 1000))
                                events.append({"event": "tool_call", "data": tool_call_event(matching, result, input_preview=json.dumps(tool_args, ensure_ascii=False))})
                                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result.get("content") or result.get("result_preview") or ""})
                            except ValueError as exc:
                                events.append({"event": "tool_call", "data": tool_call_event(matching, {"tool": tool_name, "content": "", "result_preview": "", "latency_ms": int((time.monotonic() - started) * 1000), "error": str(exc)}, status="error", input_preview=json.dumps(tool_args, ensure_ascii=False), error_code="tool_error")})
                                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": f"Error: {exc}"})
                        else:
                            events.append({"event": "tool_call", "data": tool_call_event(type("_", (), {"id": None, "name": tool_name, "type": "unknown"})(), {"tool": tool_name, "content": "", "result_preview": "", "latency_ms": 0}, status="error", input_preview="{}", error_code="tool_not_found")})
                            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": f"Tool '{tool_name}' not found"})
                        total_calls += 1
                        tools_used.append(tool_name)

            # Max rounds reached — get final answer from accumulated context
            final = self.provider.chat(messages, model=agent.model, temperature=agent.temperature, runtime_config=agent.runtime_config)
            return {
                "draft": final.content or "",
                "tool_outputs": [],
                "tool_stats": {"total_calls": total_calls, "tools_used": tools_used, "max_rounds_reached": True},
                "events": events,
            }
        if node_type == "LLM":
            if context.get("draft"):
                return self._llm_output(agent, context, context["draft"])
            messages = self._llm_messages(agent, context)
            draft = self.provider.chat(messages, model=agent.model, temperature=agent.temperature, runtime_config=agent.runtime_config).content or ""
            return self._llm_output(agent, context, draft)
        if node_type == "Answer":
            answer = (context.get("draft") or "").strip()
            if not answer:
                raise ValueError("Model returned an empty answer")
            return {"answer": answer, "citation_count": len([*context.get("sources", []), *context.get("web_sources", [])])}
        return {}

    def _stream_llm_node(self, agent, node: dict, context: dict):
        draft = context.get("draft", "")
        if draft:
            # Draft already produced by the tool-calling loop — stream as chunked text
            for index in range(0, len(draft), 24):
                yield {"event": "token", "content": draft[index : index + 24]}
            return self._llm_output(agent, context, draft)
        messages = self._llm_messages(agent, context)
        chunks = []
        for token in self.provider.chat_stream(messages, model=agent.model, temperature=agent.temperature, runtime_config=agent.runtime_config):
            chunks.append(token)
            yield {"event": "token", "content": token}
        draft = "".join(chunks)
        return self._llm_output(agent, context, draft)

    def _llm_messages(self, agent, context: dict) -> list[dict]:
        source_text = "\n".join(f"- {item['title']}: {item['snippet']}" for item in context.get("sources", []))
        web_source_text = self._web_source_text(context.get("web_sources", []))
        tool_text = "\n".join(f"- {item['tool']}: {item['content']}" for item in context.get("tool_outputs", []))
        variable_text = "\n".join(f"- {key}: {value}" for key, value in context.get("variables", {}).items())
        attachment_text = self._attachment_text(context.get("uploads", []))
        return [
            {"role": "system", "content": agent.system_prompt or "你是一个自定义智能体。"},
            *self._thinking_messages(context),
            {"role": "system", "content": f"Web search results for this turn:\n{web_source_text or 'None'}"},
            {"role": "system", "content": f"可用知识片段：\n{source_text or '无'}"},
            {"role": "system", "content": f"工具输出：\n{tool_text or '无'}"},
            {"role": "system", "content": f"用户变量：\n{variable_text or '无'}"},
            {"role": "system", "content": f"会话记忆摘要：\n{context.get('memory_summary') or '无'}"},
            {"role": "system", "content": f"本轮附件上下文：\n{attachment_text or '无'}"},
            {"role": "system", "content": f"Long-term Agent memory:\n{context.get('profile_memory') or 'None'}"},
            {"role": "user", "content": self._user_content(context["input"], context.get("uploads", []))},
        ]

    def _llm_output(self, agent, context: dict, draft: str) -> dict:
        return {
            "draft": draft,
            "used_memory": bool(context.get("memory_summary")),
            "used_profile_memory": bool(context.get("profile_memory")),
            "attachment_count": len(context.get("uploads", [])),
            "model": agent.model,
            "mock": self.provider.last_chat_mock,
            "thinking_enabled": bool(context.get("thinking_enabled")),
            "thinking_type": (context.get("thinking_status") or {}).get("type", "none"),
            "search_enabled": bool(context.get("search_enabled")),
            "search_result_count": len(context.get("web_sources", [])),
        }

    def _runtime_agent(self, agent: Agent, mode: str, user_id: int):
        # Auto-fallback to draft if published is requested but agent has never been published.
        if mode == "published" and not agent.published_version_id:
            mode = "draft"

        if mode not in {"draft", "published"}:
            raise ValueError("mode must be draft or published")
        if mode == "published":
            if not agent.published_version_id:
                raise ValueError("当前智能体还没有发布版本")
            version = self.db.get(AgentVersion, agent.published_version_id)
            if not version:
                raise ValueError("发布版本不存在")
            snapshot = version.snapshot or {}
            source = {
                "system_prompt": snapshot.get("system_prompt", agent.system_prompt),
                "model_id": snapshot.get("model_id", agent.model_id),
                "model": snapshot.get("model", agent.model),
                "temperature": snapshot.get("temperature", agent.temperature),
                "knowledge_base_ids": snapshot.get("knowledge_base_ids") or [],
                "tool_ids": [tool.get("id") for tool in snapshot.get("tools", []) if tool.get("id")],
                "workflow": snapshot.get("workflow") or default_workflow(),
                "variables": snapshot.get("variables") or [],
                "memory": normalize_memory(snapshot.get("memory")),
                "rag": normalize_rag(snapshot.get("rag")),
                "tool_policy": normalize_tool_policy(snapshot.get("tool_policy")),
                "user_model_config_id": snapshot.get("user_model_config_id", agent.user_model_config_id),
            }
        else:
            detail = get_agent_detail(self.db, agent)
            source = {
                "system_prompt": agent.system_prompt,
                "model_id": agent.model_id,
                "model": agent.model,
                "temperature": agent.temperature,
                "knowledge_base_ids": detail.get("knowledge_base_ids") or [],
                "tool_ids": [tool.get("id") for tool in detail.get("tools", []) if tool.get("id")],
                "workflow": detail.get("workflow") or default_workflow(),
                "variables": detail.get("variables") or [],
                "memory": normalize_memory(detail.get("memory")),
                "rag": normalize_rag(detail.get("rag")),
                "tool_policy": normalize_tool_policy(detail.get("tool_policy")),
                "user_model_config_id": agent.user_model_config_id,
            }

        user_model_config = self._user_model_config(user_id, source["user_model_config_id"])
        runtime_config = user_model_runtime_config(user_model_config) if user_model_config else None
        return SimpleNamespace(
            id=agent.id,
            workspace_id=agent.workspace_id,
            system_prompt=source["system_prompt"],
            model_id=source["model_id"],
            user_model_config_id=source["user_model_config_id"],
            model=(runtime_config or {}).get("chat_model") or source["model"],
            temperature=source["temperature"],
            knowledge_base_ids=source["knowledge_base_ids"],
            tool_ids=source["tool_ids"],
            workflow=source["workflow"],
            model_config=self._model_config(source["model_id"], source["model"]),
            user_model_config=user_model_config,
            runtime_config=runtime_config,
            capability_config=user_model_config or self._model_config(source["model_id"], source["model"]),
            settings={
                "variables": source["variables"],
                "memory": source["memory"],
                "rag": source["rag"],
                "tool_policy": source["tool_policy"],
            },
        )

    def _model_config(self, model_id: int | None, model_name: str | None) -> ModelConfig | None:
        return resolve_agent_model(self.db, model_id=model_id, model_name=model_name)

    def _user_model_config(self, user_id: int, config_id: int | None) -> UserModelConfig | None:
        if config_id is None:
            return None
        return resolve_user_model_config(self.db, user_id=user_id, config_id=config_id, enabled_only=True)

    def _validate_model_capabilities(self, model: ModelConfig | UserModelConfig | None, uploads: list[Upload]) -> None:
        if not model:
            return
        has_document = any(upload.kind == "document" for upload in uploads)
        if has_document and not getattr(model, "supports_document", True):
            raise ValueError("Selected model does not support document input")

    def _thinking_status(self, model: ModelConfig | UserModelConfig | None, requested: bool | None) -> dict:
        reasoning_type = str(getattr(model, "reasoning_type", "none") or "none")
        if reasoning_type not in {"native", "prompt", "none"}:
            reasoning_type = "none"
        supports_reasoning = bool(getattr(model, "supports_reasoning", False)) and reasoning_type != "none"
        label = str(getattr(model, "reasoning_label", "") or self._reasoning_label(reasoning_type))

        if not requested:
            return {
                "enabled": False,
                "requested": False,
                "type": reasoning_type,
                "label": label,
                "reason": "not_requested",
            }
        if not supports_reasoning:
            return {
                "enabled": False,
                "requested": True,
                "type": "none",
                "label": self._reasoning_label("none"),
                "reason": "model_not_supported",
            }
        return {
            "enabled": True,
            "requested": True,
            "type": reasoning_type,
            "label": label,
            "reason": "enabled",
        }

    def _thinking_messages(self, context: dict) -> list[dict]:
        status = context.get("thinking_status") or {}
        if not status.get("enabled"):
            return []
        if status.get("type") == "prompt":
            return [
                {
                    "role": "system",
                    "content": (
                        "本轮已开启深度思考模式，但当前模型使用提示词增强，不是原生推理。"
                        "请先进行更周全的分析，检查关键假设、约束、风险和反例，再给出清晰答案。"
                        "不要输出隐藏推理链，只输出必要的结论、依据和可执行步骤。"
                    ),
                }
            ]
        return [
            {
                "role": "system",
                "content": "本轮已开启原生深度思考能力。请给出经过审慎推理后的答案，不要输出隐藏推理链。",
            }
        ]

    @staticmethod
    def _reasoning_label(reasoning_type: str) -> str:
        return {"native": "深度思考", "prompt": "提示词增强", "none": "不支持"}.get(reasoning_type, "不支持")

    def _search_status(self, query: str, requested: bool | None) -> dict:
        if not requested:
            return {
                "enabled": False,
                "requested": False,
                "query": query,
                "provider": "duckduckgo_html",
                "matched_results": 0,
                "sources_emitted": False,
                "items": [],
                "sources": [],
                "reason": "not_requested",
            }
        try:
            result = web_search_service.search_web(query)
            sources = web_search_service.search_items_as_sources(result.get("items", []))
            return {
                "enabled": bool(sources),
                "requested": True,
                "query": result.get("query", query),
                "provider": result.get("provider", "duckduckgo_html"),
                "matched_results": len(sources),
                "sources_emitted": bool(sources),
                "items": result.get("items", []),
                "sources": sources,
                "latency_ms": result.get("latency_ms", 0),
                "reason": "enabled" if sources else "no_results",
            }
        except WebSearchError as exc:
            return {
                "enabled": False,
                "requested": True,
                "query": query,
                "provider": "duckduckgo_html",
                "matched_results": 0,
                "sources_emitted": False,
                "items": [],
                "sources": [],
                "reason": str(exc),
            }

    def _search_status_event(self, status: dict) -> dict:
        return {key: value for key, value in status.items() if key != "sources"}

    def _web_source_text(self, sources: list[dict]) -> str:
        lines = []
        for index, item in enumerate(sources, start=1):
            title = item.get("title") or f"Result {index}"
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            lines.append(f"{index}. {title}\nURL: {url}\nSnippet: {snippet}")
        return "\n\n".join(lines)

    def _runtime_tools(self, agent, node: dict) -> list[Tool]:
        tool_ids = getattr(agent, "tool_ids", []) or []
        if tool_ids:
            return (
                self.db.query(Tool)
                .filter(Tool.id.in_(tool_ids), Tool.enabled.is_(True))
                .order_by(Tool.id.asc())
                .all()
            )
        return []

    def _attachment_text(self, uploads: list[Upload]) -> str:
        lines = []
        for upload in uploads:
            if upload.kind == "document":
                lines.append(f"[{upload.filename}]\n{upload.text[:6000]}")
            elif upload.kind == "image":
                lines.append(f"[Image: {upload.filename}]")
        return "\n\n".join(lines)

    def _user_content(self, text: str, uploads: list[Upload]):
        image_uploads = [upload for upload in uploads if upload.kind == "image"]
        if not image_uploads:
            return text
        content = [{"type": "text", "text": text}]
        for upload in image_uploads:
            content.append({"type": "image_url", "image_url": {"url": upload.data_url}})
        return content

    def _merge_variables(self, definitions: list[dict], provided: dict) -> dict:
        merged = {}
        for definition in definitions:
            key = definition.get("key")
            if key:
                merged[key] = provided.get(key, definition.get("default_value"))
        for key, value in provided.items():
            if key not in merged:
                merged[key] = value
        return merged

    def _session_memory(self, session_id: int) -> SessionMemory | None:
        return self.db.query(SessionMemory).filter(SessionMemory.session_id == session_id).first()

    def _update_session_memory(self, session_id: int, user_message: str, answer: str, max_messages: int) -> None:
        memory = self._session_memory(session_id)
        if not memory:
            memory = SessionMemory(session_id=session_id, summary="", message_count=0)
            self.db.add(memory)
        memory.message_count += 2
        seed = f"{memory.summary}\n用户：{user_message}\n助手：{answer}".strip()
        lines = [line for line in seed.splitlines() if line.strip()]
        memory.summary = "\n".join(lines[-max_messages:])[:1200]
