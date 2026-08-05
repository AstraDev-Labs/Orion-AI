import sys
from pathlib import Path
from orion.sdk import Orion

def main():
    with Orion() as j:
        tools = [
            "shell_exec", "web_search", "think",
            "obsidian_search_notes", "obsidian_write_note",
            "play_music", "play_video"
        ]
        j._ensure_engine()
        
        test_prompts = [
            "Put on Stranger Things on Netflix",
            "Play Ted Lasso on Apple TV"
        ]
        
        for prompt in test_prompts:
            print(f"\n{'='*60}")
            print(f"PROMPT: {prompt}")
            print('='*60)
            try:
                response = j.ask(
                    prompt,
                    agent="orchestrator",
                    model="custom-orion",
                    tools=tools,
                    confirm_callback=lambda *args, **kwargs: True
                )
                print(f"\nRESULT: {response}")
            except Exception as e:
                print(f"\nERROR: {e}")
            print()

if __name__ == "__main__":
    main()
