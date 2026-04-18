import os

target_file = r"c:\Users\Tharu\OneDrive\Documents\Orion Project\backend\orion.py"

with open(target_file, "r", encoding="utf-8") as f:
    code = f.read()

# Add the helper method before process_recorded_audio
helper_code = """
    async def _get_llm_response(self, messages, tools):
        \"\"\"Unified method for streaming reasoning from Ollama or Groq.\"\"\"
        provider = os.getenv("REASONING_PROVIDER", "ollama").lower()
        if provider == "groq":
            import groq
            import json
            client = groq.AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
            try:
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
                                tool_calls_buffer[idx] = {'id': tc.id, 'function': {'name': tc.function.name, 'arguments': tc.function.arguments or ""}}
                            else:
                                if tc.function.arguments:
                                    tool_calls_buffer[idx]['function']['arguments'] += tc.function.arguments
                    elif chunk.choices and chunk.choices[0].delta.content:
                        yield {'content': chunk.choices[0].delta.content}
                
                if tool_calls_buffer:
                    yield {'tool_calls': list(tool_calls_buffer.values())}
            except Exception as e:
                print(f"[Groq Error] {e}")
                yield {'content': f"Sir, I encountered a cloud processing error: {e}"}
        else:
            response_stream = await asyncio.to_thread(
                ollama.chat,
                model=LOGIC_MODEL,
                messages=messages,
                tools=tools,
                stream=True
            )
            for chunk in response_stream:
                msg = chunk.get('message', {})
                if msg.get('tool_calls'):
                    yield {'tool_calls': msg['tool_calls']}
                elif msg.get('content'):
                    yield {'content': msg['content']}

    async def process_recorded_audio(self):"""

code = code.replace("    async def process_recorded_audio(self):", helper_code)

# Now refactor logic in both process_recorded_audio and process_text_input
ollama_block_audio = """            # 2. Reasoning (Ollama Streaming)
            response_stream = await asyncio.to_thread(
                ollama.chat,
                model=LOGIC_MODEL,
                messages=messages,
                tools=tools,
                stream=True
            )
            
            full_assistant_text = ""
            current_sentence = ""
            
            # Sentence terminators for splitting
            terminators = (".", "!", "?", "\\n")
            
            for chunk in response_stream:
                if chunk.get('message', {}).get('tool_calls'):
                    # If it's a tool call, we can't stream normally. Handle as a block.
                    msg = chunk['message']
                    messages.append(msg)
                    for tool in msg['tool_calls']:
                        name = tool['function']['name']
                        args = tool['function']['arguments']
                        print(f"[TOOL] Executing: {name}({args})")
                        result = await self.execute_tool(name, args)
                        messages.append({'role': 'tool', 'content': str(result), 'name': name})
                    
                    # Re-query for final speech
                    final_stream = await asyncio.to_thread(ollama.chat, model=LOGIC_MODEL, messages=messages, stream=True)
                    for f_chunk in final_stream:
                        token = f_chunk.get('message', {}).get('content', '')
                        full_assistant_text += token
                        current_sentence += token
                        
                        # If reached end of sentence, push to queue
                        if any(token.endswith(t) for t in terminators):
                            text_to_speak = current_sentence.strip()
                            if text_to_speak:
                                if self.on_transcription:
                                    self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                                await self.audio_queue.put(text_to_speak)
                            current_sentence = ""
                    break
                
                token = chunk.get('message', {}).get('content', '')
                full_assistant_text += token
                current_sentence += token
                
                # Check for sentence completion
                if any(token.endswith(t) for t in terminators):
                    text_to_speak = current_sentence.strip()
                    if text_to_speak:
                        if self.on_transcription:
                            self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                        await self.audio_queue.put(text_to_speak)
                    current_sentence = "" """

groq_block_audio = """            full_assistant_text = ""
            current_sentence = ""
            terminators = (".", "!", "?", "\\n")
            
            async for chunk in self._get_llm_response(messages, tools):
                if chunk.get('tool_calls'):
                    import json
                    messages.append({'role': 'assistant', 'content': '', 'tool_calls': chunk['tool_calls']})
                    for tool in chunk['tool_calls']:
                        name = tool['function']['name']
                        args = tool['function']['arguments']
                        print(f"[TOOL] Executing: {name}({args})")
                        try:
                            # Groq might stream back JSON strings that need parsing
                            if isinstance(args, str):
                                parsed_args = json.loads(args) if args else {}
                            else:
                                parsed_args = args
                            result = await self.execute_tool(name, parsed_args)
                        except Exception as e:
                            result = f"Error executing tool: {e}"
                        messages.append({'role': 'tool', 'content': str(result), 'name': name, 'tool_call_id': tool.get('id', 'call_0')})
                    
                    # Re-query
                    async for f_chunk in self._get_llm_response(messages, tools):
                        token = f_chunk.get('content', '')
                        full_assistant_text += token
                        current_sentence += token
                        if any(token.endswith(t) for t in terminators):
                            text_to_speak = current_sentence.strip()
                            if text_to_speak:
                                if self.on_transcription:
                                    self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                                await self.audio_queue.put(text_to_speak)
                            current_sentence = ""
                    break
                
                token = chunk.get('content', '')
                full_assistant_text += token
                current_sentence += token
                
                if any(token.endswith(t) for t in terminators):
                    text_to_speak = current_sentence.strip()
                    if text_to_speak:
                        if self.on_transcription:
                            self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                        await self.audio_queue.put(text_to_speak)
                    current_sentence = "" """

ollama_block_text = """            # Reasoning (Ollama Streaming)
            response_stream = await asyncio.to_thread(
                ollama.chat,
                model=LOGIC_MODEL,
                messages=messages,
                tools=tools,
                stream=True
            )
            
            full_assistant_text = ""
            current_sentence = ""
            terminators = (".", "!", "?", "\\n")
            
            for chunk in response_stream:
                if chunk.get('message', {}).get('tool_calls'):
                    msg = chunk['message']
                    messages.append(msg)
                    for tool in msg['tool_calls']:
                        name = tool['function']['name']
                        args = tool['function']['arguments']
                        print(f"[TOOL] Executing: {name}({args})")
                        result = await self.execute_tool(name, args)
                        messages.append({'role': 'tool', 'content': str(result), 'name': name})
                    
                    final_stream = await asyncio.to_thread(ollama.chat, model=LOGIC_MODEL, messages=messages, stream=True)
                    for f_chunk in final_stream:
                        token = f_chunk.get('message', {}).get('content', '')
                        full_assistant_text += token
                        current_sentence += token
                        
                        if any(token.endswith(t) for t in terminators):
                            text_to_speak = current_sentence.strip()
                            if text_to_speak:
                                if self.on_transcription:
                                    self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                                await self.audio_queue.put(text_to_speak)
                            current_sentence = ""
                    break
                
                token = chunk.get('message', {}).get('content', '')
                full_assistant_text += token
                current_sentence += token
                
                if any(token.endswith(t) for t in terminators):
                    text_to_speak = current_sentence.strip()
                    if text_to_speak:
                        if self.on_transcription:
                            self.on_transcription({'text': text_to_speak, 'type': 'jarvis_partial'})
                        await self.audio_queue.put(text_to_speak)
                    current_sentence = "" """

code = code.replace(ollama_block_audio, groq_block_audio)
code = code.replace(ollama_block_text, groq_block_audio)

with open(target_file, "w", encoding="utf-8") as f:
    f.write(code)
    
print("Refactoring completed.")
