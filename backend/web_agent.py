import os
import time
import asyncio
import base64
import ollama
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# 1. Load Environment
load_dotenv()

# 2. Configuration
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
MODEL_ID = "llama3.2" 
MOONDREAM_MODEL = "moondream"

class WebAgent:
    def __init__(self):
        self.model = MODEL_ID
        self.browser = None
        self.context = None
        self.page = None

    async def run(self, prompt, update_callback=None):
        """
        Runs the agent with the given prompt using local Ollama and Moondream.
        Returns the final summary.
        """
        print(f"[START] WebAgent (Local) started. Goal: {prompt}")
        final_response = "Agent finished."

        async with async_playwright() as p:
            # Launch browser
            self.browser = await p.chromium.launch(headless=True)
            self.context = await self.browser.new_context(
                viewport={"width": SCREEN_WIDTH, "height": SCREEN_HEIGHT}
            )
            self.page = await self.context.new_page()
            
            # Start at Google
            await self.page.goto("https://www.google.com")
            
            chat_history = [
                {"role": "system", "content": f"You are a web assistant for ORION. Goal: {prompt}. Use the provided page info to decide next steps."}
            ]

            MAX_TURNS = 8
            for turn in range(MAX_TURNS):
                print(f"--- Turn {turn + 1} ---")
                
                # 1. Capture Screenshot
                screenshot_bytes = await self.page.screenshot(type="png")
                encoded_image = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                # 2. Page Content
                try:
                    title = await self.page.title()
                    url = self.page.url
                except Exception:
                    title = "Unknown"
                    url = "Unknown"

                # 3. Ask Ollama for logic
                user_msg = f"Current URL: {url}\nPage Title: {title}\nWhat is the next step to achieve: {prompt}? (Type 'FINISH' if done)"
                chat_history.append({"role": "user", "content": user_msg})
                
                try:
                    response = ollama.chat(
                        model=self.model,
                        messages=chat_history
                    )
                    agent_reply = response['message']['content']
                    chat_history.append({"role": "assistant", "content": agent_reply})
                    print(f"[AGENT] {agent_reply}")
                except Exception as e:
                    print(f"[ERR] Ollama error: {e}")
                    break

                # Update HUD via callback
                if update_callback:
                    await update_callback(encoded_image, f"Turn {turn+1}: {agent_reply[:100]}")

                # 4. Action Execution (Simpler version for local)
                if "finish" in agent_reply.upper():
                    final_response = agent_reply
                    break
                
                # Heuristic for navigation or clicking
                if "navigate" in agent_reply.lower() and "http" in agent_reply.lower():
                    import re
                    match = re.search(r'https?://[^\s]+', agent_reply)
                    if match:
                        await self.page.goto(match.group(0))
                
                await asyncio.sleep(2)

            await self.browser.close()
            print("[CLOSE] Browser closed.")
            return final_response

if __name__ == "__main__":
    agent = WebAgent()
    asyncio.run(agent.run_task("Look up the latest news about AI"))
