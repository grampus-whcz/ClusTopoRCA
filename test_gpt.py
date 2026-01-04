import openai
 
client = openai.OpenAI(
    api_key="sk-8CwQhXLMcCdb3HtdH4oiMkf8IDM3k9G3OYM0uPUvFJ1YzqmV",  
    base_url="https://api2.qiandao.mom/v1"
)
 
response = client.chat.completions.create(
    model="gemini-2.5-pro-preview-p",  # model to send to the proxy
    messages=[{"role": "user", "content": "Who are you?"}],
)
print(response)