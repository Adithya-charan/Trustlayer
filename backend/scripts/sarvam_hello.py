"""One working Sarvam call: a chat completion with sarvam-105b-conversations. The key comes from the environment (SARVAM_API_KEY)."""
import os

from sarvamai import SarvamAI

client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)
print(response.choices[0].message.content)
