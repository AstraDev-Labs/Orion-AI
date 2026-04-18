import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
import groq

tools = [
    {
        'type': 'function',
        'function': {
            'name': 'execute_system_command',
            'description': 'Executes a system shell command.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'command': {'type': 'string', 'description': 'The shell command to execute.'},
                    'description': {'type': 'string', 'description': 'A friendly description of what it does.'}
                },
                'required': ['command', 'description']
            }
        }
    }
]

async def test_groq():
    client = groq.AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
    messages=[{"role": "user", "content": "open notepad"}]
    
    response_stream = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        tools=tools,
        stream=True
    )
    
    tool_calls_buffer = {}
    async for chunk in response_stream:
        if chunk.choices and chunk.choices[0].delta.tool_calls:
            for tc in chunk.choices[0].delta.tool_calls:
                idx = tc.index
                if idx not in tool_calls_buffer:
                    tool_calls_buffer[idx] = {'id': tc.id, 'type': 'function', 'function': {'name': tc.function.name, 'arguments': tc.function.arguments or ""}}
                else:
                    if tc.function.arguments:
                        tool_calls_buffer[idx]['function']['arguments'] += tc.function.arguments
    
    tool_calls = list(tool_calls_buffer.values())
    if tool_calls:
        print("Got tool calls:", tool_calls)
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': tool_calls})
        messages.append({'role': 'tool', 'content': 'Success', 'name': tool_calls[0]['function']['name'], 'tool_call_id': tool_calls[0].get('id', 'call_1')})
        
        try:
            stream2 = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools,
                stream=True
            )
            async for chunk in stream2:
                if chunk.choices and chunk.choices[0].delta.content:
                    print("CONTENT 2:", chunk.choices[0].delta.content)
        except Exception as e:
            print("ERROR ON REQUERY:", e)

asyncio.run(test_groq())
