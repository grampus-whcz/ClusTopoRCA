from google import genai

client = genai.Client(api_key="AIzaSyCYNE2M46yYSMgli139_9ihKdI3HGmGtkA")

response = client.models.generate_content(
    model="gemini-2.5-flash", contents="Who are you?"
)
print(response.text)