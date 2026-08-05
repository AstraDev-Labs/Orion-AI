import json
from pathlib import Path

def main():
    dataset = [
        {
            "messages": [
                {"role": "user", "content": "Orion, open Chrome."},
                {
                    "role": "assistant",
                    "content": "I will open Google Chrome for you now.",
                    "tool_calls": [
                        {
                            "id": "call_12345",
                            "type": "function",
                            "function": {
                                "name": "shell_exec",
                                "arguments": "{\"command\": \"start chrome\"}"
                            }
                        }
                    ]
                }
            ]
        },
        {
            "messages": [
                {"role": "user", "content": "What is the Sensex value?"},
                {
                    "role": "assistant",
                    "content": "Let me check the web for the current Sensex value.",
                    "tool_calls": [
                        {
                            "id": "call_67890",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": "{\"query\": \"current Sensex value BSE India\"}"
                            }
                        }
                    ]
                }
            ]
        },
        {
            "messages": [
                {"role": "user", "content": "Open my hello orion note in Obsidian."},
                {
                    "role": "assistant",
                    "content": "Searching your Obsidian vault for the hello orion note.",
                    "tool_calls": [
                        {
                            "id": "call_abcde",
                            "type": "function",
                            "function": {
                                "name": "obsidian_search_notes",
                                "arguments": "{\"query\": \"hello orion\"}"
                            }
                        }
                    ]
                }
            ]
        }
    ]
    
    out_path = Path("orion_synthetic_sft.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for item in dataset:
            f.write(json.dumps(item) + "\n")
            
    print(f"Created synthetic dataset at {out_path.absolute()}")
    print("Use this file in Google Colab if your local Traces database is empty.")

if __name__ == "__main__":
    main()
