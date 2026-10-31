# Tool Chatbot
# A terminal chatbot that remembers the conversation and can use tools.
# The model can ask this program to look up the current weather or the air
# quality of a city. The program runs the lookup and sends the result back,
# and the model uses it to write its answer.
#
# Setup:
#   1. pip install -U google-genai requests
#   2. Create a free key in Google AI Studio and save it in the GEMINI_API_KEY
#      environment variable (never write the key in the code).
#   3. Keep weather.py in the same folder, because this file imports from it.
#   4. Run: python tool_chatbot.py
#
# Optional: set WEATHER_UNITS to "fahrenheit" (the default is "celsius").
# Type "quit" or "exit" to leave.
# Note: model names and SDK details change over time, so check the
# official Gemini docs if something stops working.

import json
from google import genai
# The three lookup functions come from the weather app (weather.py)
from weather import get_coordinates, get_weather, get_air_quality
import os
import httpx
from google.genai import errors


# ---- The tools: normal Python functions the model can ask for ----
# Each tool takes the argument the model chooses and returns a dictionary.
# Failures are returned as {"error": ...} instead of crashing, so the model
# can read the problem and explain it to the user.

def get_weather_for_city(location):
    # Read the temperature unit from the WEATHER_UNITS environment variable.
    # It defaults to celsius, and any other value falls back to celsius too.
    unit = os.environ.get("WEATHER_UNITS", "celsius").lower()
    if unit not in ("celsius","fahrenheit"):
        unit = "celsius"
    symbol = "°F" if unit == "fahrenheit" else "°C"

    # Step 1: city name -> coordinates
    place = get_coordinates(location)
    if place is None:
        return {"error": f"Could not find a city called '{location}', or the lookup failed."}
    name,country,lat,lon = place

    # Step 2: coordinates -> current weather
    current = get_weather(lat,lon,unit)
    if current is None:
        return {"error": f"Found {name}, but could not get its weather right now."}
    temp,wind,observed_at,condition = current

    # Labeled keys and explicit units, so the model doesn't have to guess
    return {"city":name,"country":country,"temperature":temp,"temp_unit":symbol,"condition":condition,"wind":wind,"wind_unit":"km/h","observed_at":observed_at}

def get_air_quality_for_city(location):
    place = get_coordinates(location)
    if place is None:
        return {"error": f"Could not find a city called '{location}', or the lookup failed."}
    name, country, lat, lon = place    

    # Two different failures, checked in this order:
    # None means the request failed (checked BEFORE unpacking, which would crash on None)
    quality = get_air_quality(lat, lon)
    if quality is None:
        return {"error": f"Could not get the air quality of {name}."}

    # An empty aqi means the request worked but this place has no data
    aqi, pm25, status = quality
    if aqi is None:
        return {"error": f"No air quality data is available for {name}."}

    return {"city": name, "country": country, "aqi": aqi, "pm25": pm25,"pm25_unit": "μg/m³", "status": status}


# ---- The tool descriptions: this is all the model ever sees ----
# The model never sees the Python code above, only these descriptions.
# It reads "description" to decide WHEN to use a tool, so it needs to be clear.
# "name" must match the key in TOOLS_FUNCTIONS, and the parameter name
# ("location") must match the function's parameter.

weather_tool = {
    "type": "function",
    "name": "get_weather_for_city",
    "description": (
        "Gets the current weather for a city: temperature, wind speed, and a "
        "short condition such as 'Clear sky'. Use it whenever the user asks "
        "about the weather or temperature in a place. If the city can't be "
        "found, it returns an error message instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The name of the city, for example Berlin or New York",
            },
        },
        "required": ["location"],
    },
}

# The scale is written into the description so the model knows what the numbers mean
air_quality_tool = {
    "type": "function",
    "name": "get_air_quality_for_city",
    "description": (
        "Gets the current air quality for a city: the European Air Quality "
        "Index (AQI, where lower is better: 0-20 good, 21-40 fair, 41-60 "
        "moderate, 61-80 poor, above 80 very poor), PM2.5 in μg/m³, and a "
        "rating label. Use it when the user asks about air quality, "
        "pollution, or whether the air is clean. If the city can't be found "
        "or there is no data, it returns an error message instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "The name of the city, for example Berlin or New York",
            },
        },
        "required": ["location"],
    },
}


# Two different things, kept apart on purpose:
# TOOLS_FUNCTIONS maps a tool name to the real function. Only this program uses it.
# TOOLS_DESCRIPTIONS is the list the model reads. It is sent with every request.
# To add a tool: write the function, write its description, and add it to both.
TOOLS_FUNCTIONS = {
    "get_weather_for_city" : get_weather_for_city,
    "get_air_quality_for_city" : get_air_quality_for_city
}

TOOLS_DESCRIPTIONS = [weather_tool,air_quality_tool]


def run_tools(steps):
    # Looks through a reply for tool requests and runs them.
    # Returns one result per request. An empty list means the model asked for
    # no tools, which is the signal that its answer is ready.
    function_results = []
    for step in steps:
        if step.type == "function_call":
            try:
                # Find the real function by the name the model gave
                func = TOOLS_FUNCTIONS.get(step.name)
                if func is None:
                    # The model asked for a tool that doesn't exist
                    print(f"  Unknown tool: {step.name}")
                    result = {"error": f"Unknown tool: {step.name}"}
                else:
                    # ** turns the model's arguments into keyword arguments
                    result = func(**step.arguments)
                payload = json.dumps(result)        # inside the try, so unserializable results are caught
            except Exception as e:
                # A bug in a tool must not end the chat. The error goes to the
                # model as the result, and is printed so we can see it too.
                print(f"  tool error: {type(e).__name__}: {e}")
                payload = json.dumps({"error": f"Tool failed: {type(e).__name__}: {e}"})

            # Every tool request gets exactly one result. call_id links the
            # result to the request it answers.
            function_results.append({
                "type": "function_result",
                "name": step.name,
                "call_id": step.id,
                "result": [{"type": "text", "text": payload}],
            })
    return function_results


# ---- Settings and startup ----
client_ok = True
MODEL = "gemini-3.5-flash-lite"
MAX_ROUNDS = 5      # most tool rounds allowed per question, so a stuck model can't loop forever

try:
    client = genai.Client()   # reads GEMINI_API_KEY from the environment
except ValueError as e:
    # No key was found, so we can't chat. Explain the fix and skip the loop.
    client_ok = False
    print(f"Could not start: {e}")
    print("Check that GEMINI_API_KEY is set, then fully close and reopen VS Code.")


def main():
    # The id of the last successful reply. Sending it with the next request is
    # what gives the bot its memory. It starts as None (nothing said yet).
    # It is created inside main() on purpose: a variable that main() assigns
    # to must also be created in main(), or Python raises UnboundLocalError.
    pre_id = None

    # Main chat loop: runs until the user quits (break)
    while client_ok:
        try:
            # .strip() removes spaces, .lower() makes "QUIT" work too
            user_input = input("> ").strip()        
            if user_input.lower() in ('exit','quit'):
                break
            # Ignore empty input instead of sending it
            if not user_input:
                continue

            # First request of the turn: the question, the tool descriptions,
            # and the memory link
            response = client.interactions.create(
                model=MODEL,
                input=user_input,
                tools=TOOLS_DESCRIPTIONS,
                previous_interaction_id=pre_id
            )

            # Repeat until the model stops asking for tools. Each round runs the
            # requested tools and sends the results back, linked to the LATEST
            # reply (response.id), so the conversation stays connected.
            for _ in range(MAX_ROUNDS):
                results = run_tools(response.steps)
                if not results:
                    break       # no tools requested, so the answer is ready
                response = client.interactions.create(
                    model=MODEL,
                    previous_interaction_id=response.id,
                    tools=TOOLS_DESCRIPTIONS,
                    input=results,
                )            
            else:
                # This else belongs to the for loop. It runs only when all the
                # rounds were used without a break.
                # all rounds used: is the latest reply still asking for tools?
                if any(step.type == "function_call" for step in response.steps):
                    print("Stopped: the model kept asking for tools. Try rephrasing.")
                    # Skip the lines below, so pre_id keeps its last good value
                    continue
                # Otherwise the last reply is a normal answer that arrived on
                # the final round, so we carry on and print it.

            # These lines only run if the whole turn succeeded. If anything
            # fails, pre_id keeps its last good value and the conversation
            # can continue from where it was.
            pre_id = response.id
            text = response.output_text
            print(text if text else "(The model returned no text. Try rephrasing.)")


        # The except blocks are checked from top to bottom, so specific errors
        # come first and the general ones come last.

        # Ctrl+C or Ctrl+Z: leave cleanly instead of showing an error
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break    
        except errors.ClientError as e:
            # 4xx: you did something the API rejected (bad key, bad model, rate limit)
            if e.code == 429:
                print("Rate limit reached (free tier). Wait a bit, or try again later if you've used up the daily quota.")
            # Some key problems come with 401/403, others only mention the key
            # in the message, so we check both
            elif e.code in (401, 403) or "api key" in str(e.message).lower():
                print("Your API key looks invalid. Check GEMINI_API_KEY, then fully close and reopen VS Code.")
            else:
                print(f"The request was rejected ({e.code}): {e.message}")
        except errors.ServerError as e:
            # 5xx: the problem is on Google's side
            print(f"Google's server had a problem ({e.code}). Try again in a moment.")
        # Timeout must come before HTTPError, because it is a more specific kind
        except httpx.TimeoutException:
            print("The request timed out. Check your connection and try again.")
        except httpx.HTTPError:
            # Catch-all for network failures, such as Wi-Fi being off
            print("Could not reach Google. Check your internet connection.")    
        except Exception as e:
            # Last resort: show what happened instead of crashing the chat.
            # This must stay last, because it matches almost any error.
            print(f"Unexpected error ({type(e).__name__}): {e}")


# Runs main() only when this file is run directly,
# not when it is imported by another script.
if __name__ == '__main__':
    main()
