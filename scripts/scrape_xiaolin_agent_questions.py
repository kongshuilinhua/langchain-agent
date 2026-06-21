from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests

from xiaolin_interview_notes import LLM_NOTES, RAG_NOTES, TOOLS_NOTES


DEFAULT_URL = "https://xiaolinnote.com/ai/agent/1_whatisagent.html"
QUESTION_PATTERN = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")

STUDY_NOTES = {
    1: {
        "answer": (
            "Agent 是以大模型为决策核心、能够围绕目标持续行动的系统。普通 LLM 通常完成一次"
            "输入到输出的生成；Agent 会形成“感知、规划、行动、反馈”的循环，自主拆解任务，"
            "调用工具访问外部环境，并根据执行结果调整下一步。工具只是执行能力，是否使用工具、"
            "如何继续以及何时结束，才体现 Agent 的自主性。"
        ),
        "keywords": "自主闭环；目标拆解；工具调用；环境反馈；持续状态",
    },
    2: {
        "answer": (
            "完整 Agent 通常包含四部分：LLM 负责理解和决策；工具系统负责搜索、计算、读写数据"
            "和调用 API；记忆系统保存当前任务状态及跨任务经验；规划模块把复杂目标拆成步骤并"
            "维护执行顺序。运行时不断重复“规划、决策、执行、记录结果、再次决策”，直到完成目标。"
        ),
        "keywords": "LLM；Tools；Memory；Planning；循环执行",
    },
    3: {
        "answer": (
            "Tool 是最小执行单元，本质是带名称、描述和参数约束的函数，本身不做决策。Agent 是"
            "由 LLM 驱动的决策系统，会动态选择工具和执行路径。Workflow 是开发者预先定义好的"
            "控制流，节点可以是普通代码、LLM、Tool 或 Agent。核心区别是：Tool 只执行，Agent "
            "运行时决策，Workflow 由开发者提前决定流程。"
        ),
        "keywords": "Tool 只执行；Agent 动态决策；Workflow 固定编排",
    },
    4: {
        "answer": (
            "常见范式包括 ReAct、Plan-and-Execute 和 Reflection。Workflow 的控制流由代码预先"
            "确定，行为稳定、容易测试；Agent 把下一步决策交给 LLM，灵活但存在不确定性。生产中"
            "通常采用 Agentic Workflow：主流程使用 Workflow 保证可控，只在确实需要灵活判断的"
            "节点嵌入 Agent。"
        ),
        "keywords": "ReAct；Plan-and-Execute；Reflection；Agentic Workflow",
    },
    5: {
        "answer": (
            "推理模式可从直接回答、CoT 到 ReAct 理解。CoT 让模型显式展开多步推理，但不能原生"
            "获取外部信息；ReAct 把推理与行动交替起来，循环执行 Thought、Action、Observation。"
            "循环并不是模型自己运行，而是程序解析模型给出的动作、执行工具、写回观察结果，再次"
            "调用模型，直到模型输出最终答案或达到停止条件。"
        ),
        "keywords": "CoT；Thought；Action；Observation；代码驱动循环",
    },
    6: {
        "answer": (
            "ReAct 是边执行边规划，适合需要探索和实时调整的中短任务，但长链路容易漂移。"
            "Plan-and-Execute 先形成全局计划再逐步执行，适合复杂长任务，但计划可能不够灵活，"
            "可加入动态重规划。Reflection 不是独立执行框架，而是叠加在前两者上的质量检查机制。"
            "选型原则是：简单灵活用 ReAct，长任务用规划执行，高质量要求再加反思。"
        ),
        "keywords": "边想边做；先规划后执行；质量增强；动态重规划",
    },
    7: {
        "answer": (
            "拆分复杂任务是为了降低单次上下文和注意力负担，使每一步职责单一、可以独立验证和"
            "失败重试。固定业务可静态拆分，开放任务可让 Planner 动态生成步骤。拆分后要建立依赖"
            "关系，形成 DAG，把无依赖步骤并行执行。好的拆分还应满足完备、边界独立、结果可验证，"
            "粒度以一个可执行、可验收的原子操作为宜。"
        ),
        "keywords": "静态拆分；动态拆分；DAG；并行；完备独立可验证",
    },
    8: {
        "answer": (
            "记忆可分为感知记忆、短期记忆、长期记忆和实体记忆。感知记忆是当前原始输入；短期"
            "记忆维护本次任务的消息与工具结果；长期记忆跨任务保存经验和知识；实体记忆保存用户"
            "偏好、约束等结构化事实。设计时要回答存什么、怎么存、何时取，通常语义内容进向量库，"
            "结构化事实进关系库，并形成任务前读取、任务中使用、任务后写回的闭环。"
        ),
        "keywords": "感知；短期；长期；实体；读用写",
    },
    9: {
        "answer": (
            "短期记忆一般是 context window 中的 messages，保存当前目标、对话、工具结果和中间"
            "状态，任务结束后清理；长期记忆把有价值的信息连同 metadata 持久化，文本经 embedding "
            "写入向量数据库，使用时按语义相似度召回并注入上下文。存储粒度宜为一次完整交互或一个"
            "独立事件，避免逐句存储造成碎片，也避免整段过大引入噪声。"
        ),
        "keywords": "messages；Embedding；向量数据库；语义检索；合理粒度",
    },
    10: {
        "answer": (
            "Multi-Agent 是多个具有不同角色和工具的 Agent 协作完成同一目标。它主要解决单 Agent "
            "的三类问题：上下文容量有限、不同环节需要专业分工、独立子任务无法并行。通过把任务"
            "分给研究、编码、评审等 Worker，每个 Agent 只维护自己的干净上下文，再由调度者整合"
            "结果，可以提高专业度、并行度和复杂任务承载能力。"
        ),
        "keywords": "专业分工；上下文隔离；并行执行；Worker；结果汇总",
    },
    11: {
        "answer": (
            "流程清楚、信息量适中且不需要专业分工时优先 Single-Agent，因为链路短、成本低、容易"
            "维护。出现上下文压力、多个专业角色或可并行子任务时再升级为 Multi-Agent。多 Agent "
            "可采用中心化 Orchestrator 或去中心化协商；生产环境通常选择中心化方案，由调度者拆分、"
            "路由、汇总和处理失败，控制与追踪更清晰。"
        ),
        "keywords": "渐进演进；Orchestrator；Worker；中心化；可追踪",
    },
    12: {
        "answer": (
            "记忆压缩主要有四种：滑动窗口保留最近内容；摘要压缩用短摘要替换旧历史；重要性过滤"
            "按价值保留关键决策；结构化抽取把偏好、状态和约束转成字段。常用组合是“近期原文 + "
            "旧内容摘要 + 关键事实结构化保存”。Prompt Caching 只是复用相同前缀的计算结果，降低"
            "成本和延迟，属于计算优化，不能代替信息压缩。"
        ),
        "keywords": "滑动窗口；摘要；重要性过滤；结构化抽取；Prompt Cache",
    },
    13: {
        "answer": (
            "成熟框架适合 POC，因为能快速提供工具注册、状态管理和调用链能力；但进入生产后，过多"
            "抽象可能增加调试难度，版本升级可能破坏兼容性，通用封装也可能带来不必要的性能开销。"
            "手写核心循环能获得透明的状态、错误处理、日志和性能控制。务实做法是核心决策与执行"
            "链路自己维护，文档解析、追踪和数据库客户端等周边能力复用成熟组件。"
        ),
        "keywords": "POC；透明可控；版本风险；性能裁剪；核心手写周边复用",
    },
    14: {
        "answer": (
            "规划能力可以从 CoT、ToT、GoT 三层理解。CoT 使用一条显式推理链，成本低但走错方向"
            "后缺少纠偏；ToT 同时生成多个候选思路，持续评估和剪枝，效果更强但调用成本更高；GoT "
            "使用图结构，使不同推理分支的中间结果可以合并复用。工程上复杂任务更常采用 "
            "Plan-and-Execute，由 Planner 制定步骤、Executor 执行、Re-planner 根据反馈修订计划。"
        ),
        "keywords": "CoT；ToT；GoT；Planner；Executor；Re-planner",
    },
    15: {
        "answer": (
            "反思不是随机重试，而是“生成、评估、改进”的定向闭环。评估阶段要给出事实性、逻辑、"
            "完整性等明确标准，并允许输出 PASS；未通过时，把原任务、当前结果和具体批注一起交给"
            "改进阶段。可在关键步骤后反思，也可在任务结束后整体反思。必须设置二到三轮硬上限，"
            "只在错误代价高的节点启用，必要时由独立 Critic Agent 进行互评。"
        ),
        "keywords": "生成评估改进；PASS；最大轮次；步骤级；任务级；Critic",
    },
    16: {
        "answer": (
            "多 Agent 协作可通过消息传递或共享状态完成。消息传递耦合低，适合独立并行的 Agent；"
            "共享状态传递直接，适合前后依赖明确的流程，但要区分全局与局部状态、采用增量写入并"
            "记录错误。Agent 切换由 Orchestrator 路由：静态规则稳定便宜，LLM 动态路由灵活但成本"
            "高且可能误判。生产中通常主流程静态路由，无法匹配的边缘情况再动态兜底。"
        ),
        "keywords": "消息传递；共享状态；静态路由；动态路由；Orchestrator",
    },
}

CATEGORY_CONFIGS = {
    "agent": {
        "title": "Agent 面试题",
        "entry_url": "https://xiaolinnote.com/ai/agent/1_whatisagent.html",
        "path_prefix": "/ai/agent/",
        "output_stem": "xiaolin-agent-questions",
    },
    "rag": {
        "title": "RAG 面试题",
        "entry_url": "https://xiaolinnote.com/ai/rag/1_whatisrag.html",
        "path_prefix": "/ai/rag/",
        "output_stem": "xiaolin-rag-questions",
    },
    "tools": {
        "title": "LLM 工具调用面试题",
        "entry_url": "https://xiaolinnote.com/ai/tools/1_function_calling.html",
        "path_prefix": "/ai/tools/",
        "output_stem": "xiaolin-tools-questions",
    },
    "llm": {
        "title": "大模型工程面试题",
        "entry_url": "https://xiaolinnote.com/ai/llm/what_is_llm.html",
        "path_prefix": "/ai/llm/",
        "output_stem": "xiaolin-llm-questions",
    },
}

CATEGORY_NOTES = {
    "agent": STUDY_NOTES,
    "rag": RAG_NOTES,
    "tools": TOOLS_NOTES,
    "llm": LLM_NOTES,
}


@dataclass(frozen=True)
class Question:
    number: int
    title: str
    url: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag != "a" or self._href is not None:
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        text = " ".join("".join(self._text_parts).split())
        self.links.append((self._href, text))
        self._href = None
        self._text_parts = []


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; study-list-scraper/1.0)"},
        timeout=20,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def extract_questions(
    html: str, source_url: str, path_prefix: str
) -> list[Question]:
    parser = LinkParser()
    parser.feed(html)

    source_host = urlparse(source_url).netloc
    questions_by_number: dict[int, Question] = {}

    for href, text in parser.links:
        match = QUESTION_PATTERN.match(text)
        if not match:
            continue

        absolute_url, fragment = urldefrag(urljoin(source_url, href))
        parsed_url = urlparse(absolute_url)
        if fragment or parsed_url.netloc != source_host:
            continue
        if not parsed_url.path.startswith(path_prefix):
            continue

        number = int(match.group(1))
        questions_by_number.setdefault(
            number,
            Question(number=number, title=match.group(2), url=absolute_url),
        )

    return [questions_by_number[number] for number in sorted(questions_by_number)]


def question_markdown_lines(
    questions: list[Question], notes: dict[int, dict[str, str]]
) -> list[str]:
    lines: list[str] = []
    for question in questions:
        note = notes[question.number]
        lines.extend(
            [
                f"## {question.number}. {question.title}",
                "",
                f"**背诵答案：** {note['answer']}",
                "",
                f"**关键词：** {note['keywords']}",
                "",
                f"**原文：** {question.url}",
                "",
            ]
        )
    return lines


def write_category_markdown(
    category_title: str,
    questions: list[Question],
    notes: dict[int, dict[str, str]],
    source_url: str,
    output_path: Path,
) -> None:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        f"# {category_title}背诵清单",
        "",
        f"- 来源：{source_url}",
        f"- 抓取时间：{generated_at}",
        f"- 题目数量：{len(questions)}",
        "- 说明：答案为根据原文主题整理的精炼背诵版，并非网页全文转载。",
        "",
    ]
    lines.extend(question_markdown_lines(questions, notes))
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_combined_markdown(
    category_results: list[
        tuple[str, list[Question], dict[int, dict[str, str]], str]
    ],
    output_path: Path,
) -> None:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    total = sum(len(questions) for _, questions, _, _ in category_results)
    lines = [
        "# 大模型面试题完整背诵稿",
        "",
        f"- 抓取时间：{generated_at}",
        f"- 栏目数量：{len(category_results)}",
        f"- 题目总数：{total}",
        "- 说明：答案为根据原文主题整理的精炼背诵版，并非网页全文转载。",
        "",
    ]
    for category_title, questions, notes, source_url in category_results:
        lines.extend(
            [
                f"# {category_title}",
                "",
                f"- 来源：{source_url}",
                f"- 本栏题数：{len(questions)}",
                "",
            ]
        )
        lines.extend(question_markdown_lines(questions, notes))
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(
    rows: list[tuple[str, Question, dict[str, str]]], output_path: Path
) -> None:
    with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            [
                "方向",
                "序号",
                "题目",
                "背诵答案",
                "关键词",
                "背诵状态",
                "我的答案",
                "来源链接",
            ]
        )
        for category_title, question, note in rows:
            writer.writerow(
                [
                    category_title,
                    question.number,
                    question.title,
                    note["answer"],
                    note["keywords"],
                    "未背诵",
                    "",
                    question.url,
                ]
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取小林面试笔记四个大模型栏目并生成精炼背诵清单。"
    )
    parser.add_argument(
        "--category",
        choices=["all", *CATEGORY_CONFIGS],
        default="all",
        help="生成全部栏目或指定栏目",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs"),
        help="Markdown 和 CSV 输出目录",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    category_keys = (
        list(CATEGORY_CONFIGS)
        if args.category == "all"
        else [args.category]
    )
    category_results = []
    combined_rows: list[tuple[str, Question, dict[str, str]]] = []

    for category_key in category_keys:
        config = CATEGORY_CONFIGS[category_key]
        notes = CATEGORY_NOTES[category_key]
        html = fetch_html(config["entry_url"])
        questions = extract_questions(
            html, config["entry_url"], config["path_prefix"]
        )
        if not questions:
            raise RuntimeError(f"未找到题目：{config['title']}")

        found_numbers = {question.number for question in questions}
        missing_notes = sorted(found_numbers - notes.keys())
        extra_notes = sorted(notes.keys() - found_numbers)
        if missing_notes or extra_notes:
            raise RuntimeError(
                f"{config['title']} 答案覆盖不一致："
                f"缺少 {missing_notes}，多余 {extra_notes}"
            )

        markdown_path = args.output_dir / f"{config['output_stem']}.md"
        csv_path = args.output_dir / f"{config['output_stem']}.csv"
        write_category_markdown(
            config["title"],
            questions,
            notes,
            config["entry_url"],
            markdown_path,
        )
        category_rows = [
            (config["title"], question, notes[question.number])
            for question in questions
        ]
        write_csv(category_rows, csv_path)
        category_results.append(
            (config["title"], questions, notes, config["entry_url"])
        )
        combined_rows.extend(category_rows)
        print(f"{config['title']}: {len(questions)} 道")
        print(f"  Markdown: {markdown_path.resolve()}")
        print(f"  CSV: {csv_path.resolve()}")

    if args.category == "all":
        combined_markdown_path = (
            args.output_dir / "xiaolin-interview-questions.md"
        )
        combined_csv_path = args.output_dir / "xiaolin-interview-questions.csv"
        write_combined_markdown(category_results, combined_markdown_path)
        write_csv(combined_rows, combined_csv_path)
        print(f"总题数: {len(combined_rows)}")
        print(f"总 Markdown: {combined_markdown_path.resolve()}")
        print(f"总 CSV: {combined_csv_path.resolve()}")


if __name__ == "__main__":
    main()
