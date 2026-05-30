import requests
import json
from core.db.session import SessionLocal
from core.db.models import Agent, User, WorkspaceMember

def main():
    db = SessionLocal()
    try:
        agent = db.query(Agent).first()
        if not agent:
            print("No agent found in DB")
            return
        print(f"Testing with Agent ID: {agent.id} | Name: {agent.name}")
        
        from core.runtime.workflow import WorkflowRunner
        from core.db.models import Session
        
        # Let's create a dummy session
        session = Session(workspace_id=agent.workspace_id, agent_id=agent.id, user_id=agent.created_by, title="Test Session")
        db.add(session)
        db.commit()
        
        print("\n--- Testing Direct Workflow Python execution with mode='published' ---")
        runner = WorkflowRunner(db)
        try:
            for event in runner.run_events(agent=agent, chat_session=session, user_message="hello", mode="published"):
                pass
        except Exception as e:
            print(f"Expected failure in published mode: {e}")
            
        print("\n--- Testing Direct Workflow Python execution with mode='draft' ---")
        try:
            events_count = 0
            for event in runner.run_events(agent=agent, chat_session=session, user_message="hello", mode="draft"):
                events_count += 1
                if event["event"] == "complete":
                    print(f"Draft mode completed! Answer: {event.get('answer')}")
            print(f"Total events in draft mode: {events_count}")
        except Exception as e:
            print(f"Error in draft mode: {e}")
            
    finally:
        db.close()

if __name__ == "__main__":
    main()
