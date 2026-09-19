"""uv run --env-file .env python examples/run.py --model jev --url URL --goal 'A narrow goal'
uv run --env-file .env python examples/run.py --model kev --url URL --goal 'A narrow goal'
"""

import argparse

from jev_ultrafast import Agent
from jev_ultrafast.cli_backend import add_model_arguments, apply_model_arguments, load_env

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--goal", action="append", required=True, help="Repeat for an ordered list of goals.")
add_model_arguments(parser)
args = parser.parse_args()
load_env()
backend = apply_model_arguments(args)
print(f"Model: {args.model} ({backend})")

with Agent(args.url, args.goal) as agent:
    for state in agent.run():
        print(f"{state['elapsed_ms']:>5} ms  {len(state['history'])} actions  {state['status']}")
    print(state["page"]["url"])
