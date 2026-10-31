# Tool Chatbot

A terminal chatbot in Python that remembers the conversation and can use tools.
The model can ask the program to look up the **current weather** or the **air quality** of any city.
The program runs the lookup, sends the result back, and the model uses it to answer.

It uses the Gemini API (free tier) and the free [Open-Meteo](https://open-meteo.com/) data, which needs no API key.

## Features

- Chat in the terminal, with memory across questions ("and in Paris?" works)
- Two tools: current weather and air quality
- The model decides when a tool is needed, and can use several in one answer (for example, comparing two cities)
- Repeats tool rounds until the model has what it needs, with a limit so it can never loop forever
- Tool failures are sent back to the model as data, so a bad lookup never ends the chat
- Clear messages for a missing or invalid key, rate limits, server problems, timeouts, and no internet
- Type `quit` or `exit` (any capitalization) to leave, or press Ctrl+C

## Requirements

- Python 3.9 or newer
- The `google-genai` and `requests` libraries
- A free Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey)
- `weather.py` in the same folder (see below)

```bash
pip install -U google-genai requests
```

This project imports its lookup functions (`get_coordinates`, `get_weather`, `get_air_quality`) from `weather.py`, which comes from my weather app project. Keep both files in the same folder.

## Setup: API key

The key is read from the `GEMINI_API_KEY` environment variable.
**Never write the key in the code or upload it to GitHub.**

**Windows (PowerShell), for the current window only:**

```powershell
$env:GEMINI_API_KEY="your-key-here"
```

**Windows, saved for future windows:**

```powershell
setx GEMINI_API_KEY "your-key-here"
```

After using `setx`, fully close and reopen your terminal or VS Code. Programs only read environment variables when they start, so an already-open window will not see the new value.

**macOS / Linux:**

```bash
export GEMINI_API_KEY="your-key-here"
```

## Usage

```bash
python tool_chatbot.py
```

Example (illustrative):

```
> hi, I'm Sam
Hi Sam! How can I help you today?
> what's the weather in Berlin?
It's currently 14.2 °C and partly cloudy in Berlin, Germany, with a light wind.
> and in Paris?
In Paris it's 16.0 °C and overcast.
> compare the air quality of both
Berlin: AQI 18 (Good). Paris: AQI 35 (Fair). Berlin's air is cleaner right now.
> quit
```

The numbers above are only an example. Real answers use live data.

## The tools

| Tool | What it does | Input | Returns |
|---|---|---|---|
| `get_weather_for_city` | Current weather for a city | `location` (city name) | temperature and unit, condition, wind speed, observation time |
| `get_air_quality_for_city` | Current air quality for a city | `location` (city name) | European AQI, PM2.5, and a rating |

If a city is not found, or there is no data for it, the tool returns an error message and the model explains it in plain words.

## How it works

1. Your question is sent to the model together with a **description** of each tool. The model never sees the Python code, only these descriptions.
2. If the model needs a tool, it replies with a request (a tool name and arguments) instead of an answer.
3. The program runs the matching function and sends the result back.
4. Steps 2 and 3 repeat until the model replies without asking for a tool, up to `MAX_ROUNDS` times.
5. The final text is printed.

```
question → request → [ run tools → send results ] repeated → answer
                            stops when no tools are requested
```

**Memory:** the API does not remember anything between requests on its own. Each reply has an `id`, and the program sends the id of the last successful reply with the next request, so the conversation continues. The id is only saved after a whole question succeeds, so a failed request never corrupts the conversation.

**Round limit:** if the model is still asking for tools after `MAX_ROUNDS` rounds, the program prints a message, keeps the last good conversation point, and waits for the next question.

## Adding a new tool

1. Write a normal Python function that takes the model's argument and returns a dictionary (return `{"error": ...}` on failure).
2. Write its description dictionary (name, what it does and when to use it, and its parameters).
3. Add it to both `TOOLS_FUNCTIONS` (name to function) and `TOOLS_DESCRIPTIONS` (the list the model reads).

The chat loop itself does not change.

## Settings

| Setting | Where | Default |
|---|---|---|
| `WEATHER_UNITS` | environment variable (`celsius` or `fahrenheit`) | `celsius` |
| `MODEL` | constant in `tool_chatbot.py` | the model name set in the file |
| `MAX_ROUNDS` | constant in `tool_chatbot.py` | `5` |

## Error handling

| Situation | What the program does |
|---|---|
| No API key at startup | Prints how to set it and does not start the chat |
| Rate limit (429) | Tells you to wait, or to try again later if the daily quota is used up |
| Invalid key (401/403, or the message mentions the key) | Suggests checking `GEMINI_API_KEY` |
| Any other rejected request | Shows the real error code and message |
| Problem on Google's side (5xx) | Asks you to try again in a moment |
| Timeout or no internet | Says so, and the chat keeps going |
| A tool fails or crashes | The error is printed, sent to the model, and the chat keeps going |
| The model asks for a tool that does not exist | Reported to the model as "Unknown tool" |
| Anything unexpected | Shows the error type and message, and keeps the chat running |

## Notes

- Free tiers have rate limits, and the limits vary by model. You can see yours in Google AI Studio. A question that uses tools sends more than one request, so it counts more than once.
- Do not send private or sensitive information through a free tier.
- Model names and SDK details change over time. If something stops working, check the current [Gemini API docs](https://ai.google.dev/gemini-api/docs) and update the model in the file.

## What I practiced

- Function calling: describing tools to a model and running them for it
- Keeping conversation state between requests
- Writing a loop that repeats until a stop signal, with a safety limit
- Returning errors as data instead of crashing
- Handling specific errors with `try/except`, ordered from specific to general
- Reading secrets from environment variables
