from core.db.session import SessionLocal
from core.db.models import Tool
from core.services.tools import BUILTIN_TOOLS

def main():
    print(f"BUILTIN_TOOLS count: {len(BUILTIN_TOOLS)}")
    print(f"BUILTIN_TOOLS keys: {list(BUILTIN_TOOLS.keys())}")
    
    db = SessionLocal()
    try:
        for name, impl in BUILTIN_TOOLS.items():
            tool = db.query(Tool).filter(Tool.name == name, Tool.type == "builtin").first()
            if tool:
                print(f"Found existing builtin tool: {name}")
                tool.description = impl["description"]
                tool.label = name
                tool.enabled = True
            else:
                print(f"Adding new builtin tool: {name}")
                db.add(Tool(name=name, label=name, description=impl["description"], schema={}, type="builtin", enabled=True))
        
        # Upsert web_search
        search_tool = db.query(Tool).filter(Tool.name == "web_search").first()
        if search_tool:
            search_tool.type = "builtin_search"
            search_tool.label = "Web Search"
            search_tool.description = "Built-in web search adapter for Agent tools"
        else:
            db.add(Tool(name="web_search", label="Web Search", description="Built-in web search adapter for Agent tools", schema={}, type="builtin_search"))

        db.commit()
        print("Commit completed successfully")
        
        tools = db.query(Tool).all()
        print(f"Total tools in DB now: {len(tools)}")
        for t in tools:
            print(f"ID: {t.id} | Name: {t.name} | Label: {t.label} | Type: {t.type} | Enabled: {t.enabled}")
    except Exception as e:
        print(f"Exception: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
