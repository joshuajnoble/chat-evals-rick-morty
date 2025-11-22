import os
import json
import base64

from agents import Agent, WebSearchTool, Runner, function_tool
from deepeval.tracing import observe

import chainlit as cl # pyright: ignore[reportMissingImports]

import prompts, graphql_retriever
from deepeval.test_case import LLMTestCase
from deepeval.tracing import observe, update_current_span, update_current_trace

from deepeval.tracing import observe
from deepeval.dataset import Golden, EvaluationDataset
from deepeval.metrics import TaskCompletionMetric
from deepeval.test_case import LLMTestCase, ToolCall

from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams

@function_tool
def write_to_storage(type: str, entity: str, details: str) -> None:

    """ Write to one object in our JSON files. In practice this would be a lot smarter """

    # Store details in the appropriate JSON file.
    filename = f'{type}.json'
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            data = json.load(f)
    else:
        data = []

    entity_to_update = [item for item in data[type]['results'] if item.get('name') == entity]
    entity_to_update[0]["detail"] = details

    with open(filename, 'w') as f:
        json.dump(data, f)

    return f"Successfully stored detail {details} for {entity} in {type}."

@function_tool
def read_from_storage(type: str, entity: str) -> str:

    """ Read from our JSON files. In practice this would be a lot smarter """

    print(" read from storage called ", type, entity)

    # Read details from the appropriate JSON file.
    filename = f'{type}.json'
    if not os.path.exists(filename):
        return []

    with open(filename, 'r') as f:
        data = json.load(f)

    # Filter details for the specified entity.
    if type == "locations" or type == "characters":
        results = [item for item in data[type]['results'] if item.get('name') == entity]
    if type == "episodes":
        results = [item for item in data[type]['results'] if (item.get('name') == entity or item.get('air_date') == entity or item.get('episode') == entity)]

    return json.dumps(results)

def retrieve_all_data() -> None:
    """ Grab all the initial data if we haven't done it yet """
    graphql_retriever.fetch_and_save(graphql_retriever.CHARACTERS)
    graphql_retriever.fetch_and_save(graphql_retriever.LOCATIONS)
    graphql_retriever.fetch_and_save(graphql_retriever.EPISODES)

handoffs = []

# handles looking in files
storage_agent = Agent(
    name="Storage Agent",
    instructions=prompts.storage_instructions,
    model="gpt-5",
    tools=[write_to_storage, read_from_storage],
    handoff_description="Read or write to the local storage of locations, characters, and episodes."
)

handoffs.append(storage_agent)

# handles triaging the chat with end users
chat_agent = Agent(
    name="Chat triage agent",
    instructions=prompts.chat_triage,
    handoffs=handoffs,
    model="gpt-5"
)

@cl.action_callback("action_button")
async def on_action(action):

    """ This is called when the user types in Evaluation or Run Evaluation and then hits the button """

    # existing functions we want to use in evaluation
    read_tool = ToolCall(name="read_from_storage", arguments={})
    write_tool = ToolCall(name="write_to_storage", arguments={})

    goldens=[Golden(input="Who lives on the location 'Purge Planet'?", expected_tools=[read_tool], expected_output="Arthricia, General Store Owner, Lighthouse Keeper, Purge Planet Ruler")]
            # Golden(input="Save that the location 'Anatomy Park' is 'totally sweet'", expected_tools=[write_tool], expected_output="Successfully stored detail 'totally sweet' for Anatomy Park in locations."),
            # Golden(input="Was 'Summer Smith' in the episode 'Meeseeks and Destroy'?", expected_tools=[read_tool], expected_output="Yes")]
    
    # Initialize GEval
    correctness_metric = GEval(
        name="Correctness",
        criteria="Determine whether the actual output is factually correct based on the expected output.",
        evaluation_steps=[
            "Check whether the facts in 'actual output' contradicts any facts in 'expected output'",
            "You should also heavily penalize omission of detail",
            "Vague language, or contradicting OPINIONS, are OK"
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
    )

    
    # Initialize task metric
    task_completion = TaskCompletionMetric(threshold=0.5, model="gpt-4o")

    eval_results = ""

    # Loop through dataset
    for golden in goldens:
        response = await Runner.run(chat_agent, golden.input)
        test_case = LLMTestCase(
            input=golden.input, expected_output=golden.expected_output, actual_output=response.final_output
        )

        correctness_metric.measure(test_case)

        eval_results = eval_results + f" Correctness score: {correctness_metric.score} \n reason: {correctness_metric.reason} \n"

        # get all of the tools that were called
        tools_called = []
        for resp in response.raw_responses:
            outputs = resp.output
            for o in outputs:
                if(o.type == "function_call"):
                    if(o.name == "write_to_storage"):
                        tools_called.append(write_tool)
                    if(o.name == "read_from_storage"):
                        tools_called.append(read_tool)

        task_case = LLMTestCase(
            input=golden.input, 
            expected_output=golden.expected_output, 
            actual_output=response.final_output, 
            expected_tools=golden.expected_tools, 
            tools_called=tools_called
        )

        task_completion.measure(task_case)
        print(task_completion.score, task_completion.reason)

        eval_results = eval_results + f" Task score: {task_completion.score} \n reason: {task_completion.reason} \n"

    eval_reponse = cl.Message(author="assistant", content=eval_results)
    await eval_reponse.send()


@cl.on_chat_start
async def start():

    """ CL boilerplate to start the app. Only thing of note is storing the JSON files if they don't exist """

    cl.user_session.set(
        "message_history",
        [],
    )

    settings = {
        "show_tool_execution": True,
        "show_reasoning_summary": True,
    }
    cl.user_session.set("settings", settings)

    # should more clever about this in the future
    if not os.path.exists("locations.json"):
        retrieve_all_data()



@cl.on_message
async def message_handler(message: cl.Message):

    """ CL event handler for a new message """

    message_history = cl.user_session.get("message_history")
    message_history.append({"role": "user", "content": message.content})

    if("evaluation" in message.content.lower()):

        actions = [
            cl.Action(name="action_button", payload={"value": "example_value"}, label="Run offline DeepEval evalution.")
        ]
        await cl.Message(content="If you'd like to run evaluation click: ", actions=actions).send()

    else:

        response = await Runner.run(chat_agent, message.content)

        agent_reponse = cl.Message(author="assistant", content=response.final_output)
        await agent_reponse.send()
        
        # add the new message to history 
        cl.user_session.set("message_history", message_history)


@cl.on_chat_end
def cleanup():
    """Cleanup chat session resources"""
    pass