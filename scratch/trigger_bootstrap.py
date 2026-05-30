from core.db.session import SessionLocal
from core.services.bootstrap import ensure_builtin_tools

def main():
    db = SessionLocal()
    try:
        ensure_builtin_tools(db)
        print("upsert completed successfully")
    except Exception as e:
        print(f"Error during upsert: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
