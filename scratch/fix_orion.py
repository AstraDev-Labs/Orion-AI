import re
import os

target_file = r'c:\Users\Tharu\OneDrive\Documents\Orion Project\backend\orion.py'

with open(target_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add tool schema
new_tool_schema = """
get_screen_tool = {
    "name": "get_screen",
    "description": "Captures a screenshot of the current computer screen and returns it as an image frame for the AI to analyze.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    }
}

execute_system_command_tool = {
    "name": "execute_system_command",
    "description": "Executes a system shell command on the user's PC. Use this to open applications, start processes, or perform system tasks (e.g., 'start notepad', 'start chrome spotify.com'). Always provide a friendly description of what the command will do.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {
                "type": "STRING",
                "description": "The shell command to execute (Windows CMD/PowerShell)."
            },
            "description": {
                "type": "STRING",
                "description": "A human-readable description of what this command will do."
            }
        },
        "required": ["command", "description"]
    }
}
"""

if 'execute_system_command_tool' not in content:
    content = content.replace('get_screen_tool = {', new_tool_schema)

# 2. Add to tools list
if 'execute_system_command_tool' not in content: # Safety check
    content = content.replace('get_screen_tool\n', 'get_screen_tool,\n            execute_system_command_tool\n')

# 3. Add handle_execute_command_request and _calculate_rms methods to AudioLoop
new_methods = """
    async def handle_execute_command_request(self, command, description, call_id):
        \"\"\"Executes a Windows shell command and returns the result.\"\"\"
        print(f"[JARVIS DEBUG] [TOOL] Executing system command: {command} (Description: {description})")
        try:
            import subprocess
            # We use subprocess.Popen to launch applications without blocking the audio loop
            process = await asyncio.to_thread(subprocess.Popen, command, shell=True)
            
            # Send tool response back to Gemini
            await self.session.send_tool_response(
                function_responses=[types.FunctionResponse(
                    name="execute_system_command",
                    id=call_id,
                    response={"result": f"Successfully executed command: {description}"}
                )]
            )
            print(f"[JARVIS DEBUG] [TOOL] Command executed successfully.")
        except Exception as e:
            print(f"[JARVIS DEBUG] [TOOL] Failed to execute command: {e}")
            await self.session.send_tool_response(
                function_responses=[types.FunctionResponse(
                    name="execute_system_command",
                    id=call_id,
                    response={"error": str(e)}
                )]
            )

    def _calculate_rms(self, data):
        \"\"\"Helper to calculate RMS level of a PCM audio buffer.\"\"\"
        import struct
        import math
        count = len(data) // 2
        if count > 0:
            shorts = struct.unpack(f"<{count}h", data)
            sum_squares = sum(float(s)**2 for s in shorts)
            return int(math.sqrt(sum_squares / count))
        return 0

"""

# Insert before def get_input_devices():
if '_calculate_rms' not in content:
    content = content.replace('def get_input_devices():', new_methods + 'def get_input_devices():')

# 4. Add tool dispatch in handle_tool_call (if it exists) or within receive_audio
# Let's find where tool calls are handled.
if 'if name == "generate_cad":' in content:
    content = content.replace('if name == "generate_cad":', 'if name == "execute_system_command":\n                await self.handle_execute_command_request(args.get("command"), args.get("description"), call_id)\n            elif name == "generate_cad":')

with open(target_file, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully applied patches to orion.py")
