import json
from pathlib import Path
from orion.traces.store import TraceStore
from orion.learning.training.data import TrainingDataMiner

def main():
    db_path = Path.home() / ".orion" / "traces.db"
    if not db_path.exists():
        print(f"Error: Trace database not found at {db_path}")
        return

    print(f"Loading traces from {db_path}...")
    store = TraceStore(db_path)
    
    # Retroactively label recent successful traces so they can be mined
    traces = store.list_traces(limit=1000)
    updated_count = 0
    for t in traces:
        print(f"Trace {t.trace_id}: outcome={t.outcome}, feedback={t.feedback}")
        # If the outcome was successful but feedback is missing/low, boost it to 1.0 for behavioral cloning
        if t.outcome in ("success", None) and (t.feedback is None or t.feedback < 0.7):
            store.update_feedback(t.trace_id, 1.0)
            updated_count += 1
            
    if updated_count > 0:
        print(f"Retroactively labeled {updated_count} successful traces with 1.0 feedback.")

    # Mine SFT pairs
    miner = TrainingDataMiner(store, min_quality=0.7)
    sft_pairs = miner.extract_sft_pairs()
    
    if not sft_pairs:
        print("No SFT pairs extracted. Make sure you have completed at least one successful voice command.")
        return
        
    print(f"Extracted {len(sft_pairs)} high-quality SFT pairs.")
    
    # Save to JSONL for Unsloth
    out_path = Path("orion_sft_dataset.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for pair in sft_pairs:
            # We want to train the model to map 'input' to 'output'
            # Format as HuggingFace conversational dataset
            line = {
                "messages": [
                    {"role": "user", "content": pair["input"]},
                    {"role": "assistant", "content": pair["output"]}
                ]
            }
            f.write(json.dumps(line) + "\n")
            
    print(f"Successfully saved training dataset to: {out_path.absolute()}")

if __name__ == "__main__":
    main()
