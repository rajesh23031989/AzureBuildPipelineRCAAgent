import os
from openai import OpenAI

endpoint = "https://rasikadevale91-4455-resource.services.ai.azure.com"

client = OpenAI(
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    base_url=f"{endpoint}/openai/v1/",
)

response = client.chat.completions.create(
    model="gpt-4.1-nano",
    messages=[
        {
            "role": "user",
            "content": "Reply with exactly: Azure connection works"
        }
    ],
    max_tokens=20,
)

print(response.choices[0].message.content)
