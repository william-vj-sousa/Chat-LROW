import requests

gbt_URL = "http://localhost:4891/v1/chat/completions"

prompt = (
    "Pretend you are a French teacher. "
    "You are teaching a class of beginner students. "
    "You are answering questions they have about grammar. "
    "After every response, correct them on their grammar, spelling, "
    "and make suggestions about tone."
)

# The mem
messages = [
    {"role": "system", "content": prompt}
]

print("Type your question or prompt for the model.")
print("Type 'exit' to end.\n")

while True:
    user_input = input("> ")

    if user_input.lower() == "exit":
        break

    messages.append({"role": "user", "content": user_input})

    response = requests.post(
        gbt_URL,
        json={
            "model": "Phi-3 Mini Instruct",  # MUST match /v1/models <======= VERY VERY IMPORTANT
            "messages": messages,
            "max_tokens": 300,
            "temperature": 0.7
        },
        timeout=120
    )

    if response.status_code != 200:
        print("ERROR:", response.text)
        continue

    data = response.json()
    reply = data["choices"][0]["message"]["content"]

    messages.append({"role": "assistant", "content": reply})
    print("\nFrench Teacher:\n", reply, "\n")
