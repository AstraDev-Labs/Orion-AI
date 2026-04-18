import json
import os
import time

class MemoryManager:
    def __init__(self, storage_path="memory.json"):
        self.storage_path = storage_path
        self.memory = self._load_memory()

    def _load_memory(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    return json.load(f)
            except:
                return {"facts": [], "short_term": []}
        return {"facts": [], "short_term": []}

    def save_memory(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.memory, f, indent=4)

    def add_fact(self, fact):
        self.memory["facts"].append({
            "content": fact,
            "timestamp": time.time()
        })
        self.save_memory()

    def add_interaction(self, user_text, assistant_text):
        self.memory["short_term"].append({
            "user": user_text,
            "assistant": assistant_text,
            "timestamp": time.time()
        })
        # Keep last 20 interactions
        if len(self.memory["short_term"]) > 20:
            self.memory["short_term"].pop(0)
        self.save_memory()

    def get_context(self):
        facts_str = "\n".join([f"- {f['content']}" for f in self.memory["facts"]])
        history_str = "\n".join([f"User: {h['user']}\nORION: {h['assistant']}" for h in self.memory["short_term"]][-5:])
        return f"Long-term Facts:\n{facts_str}\n\nRecent History:\n{history_str}"

