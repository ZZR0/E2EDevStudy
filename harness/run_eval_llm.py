import copy
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

# 添加父目录到模块搜索路径
import json
import argparse
import time
import litellm
from loguru import logger
from utils.utils import load_file, save_file
from utils.constants import apply_patch
import re
import concurrent.futures
from tqdm import tqdm
import asyncio
from collections import Counter

# 添加文件日志记录器
log_file_path = "evaluation.log"
if os.path.exists(log_file_path):
    os.remove(log_file_path)  # 删除旧的日志文件
logger.add(
    log_file_path,
    rotation="100 MB",
    level="INFO",
    format="{time} {level} [{function}:{line}] {message}",
    enqueue=True,
)

REFERENCE_DIR = "./data/repos"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_KEY = GEMINI_API_KEY.split(",")

DEFINITION_MAST = """1.1 Disobey Task Specification: 
This error occurs when an agent or system fails to adhere to specified constraints, guidelines, or requirements associated with a particular task. Non-compliance can result from unclear, incomplete, or ambiguous instructions provided by the user, system prompts, or task descriptions. It may also arise from an agent's inadequate ability to interpret or apply constraints effectively. Consequences of poor task constraint compliance include incorrect, suboptimal, or irrelevant outputs, reduced system performance and increased resource consumption.

1.2 Disobey Role Specification: 
Failure to adhere to the defined responsibilities and constraints of an assigned role, potentially leading to an agent behaving like another.

1.3 Step Repetition: 
Step repetition occurs when an agent or system unnecessarily repeats a phase, a task, a stage that have already been completed. Such redundancy can arise from inadequate state or context tracking, inefficient workflow management, unclear or ambiguous instructions, or failure to recognize completed tasks.

An example of step repetition is in the following Hyperagent trace where the Planner repeated exactly the same thought twice. 

[...]
HyperAgent_matplotlib__matplotlib-23563 - INFO - Planner's Response: Thought: To address this issue, we need to understand the root cause of the 'Line3D' object not having the '_verts3d' attribute. This error typically occurs when the data passed to the plot function is invalid or when there's an issue with the 3D rendering. Let's start by examining the code and reproducing the issue.
[...]
HyperAgent_matplotlib__matplotlib-23563 - INFO - Planner's Response: Thought: To address this issue, we need to understand the root cause of the 'Line3D' object not having the '_verts3d' attribute. This error typically occurs when the data passed to the plot function is invalid or when there's an issue with the 3D rendering. Let's start by examining the code and reproducing the issue.
[...]
Intern Name: Codebase Editor
Subgoal: Please prepare a response for the user with the following content:
1. Explain the identified issue and recommend updating matplotlib to version 3.5.1 or later.
2. Provide a modified version of their code that attempts to work around the issue.
3. Suggest an alternative plotting method using scatter plots instead of lines.
[...]

1.4 Loss of Conversation History: 
Unexpected context truncation, disregarding recent interaction history and reverting to an antecedent conversational state.

1.5 Unaware of Termination Conditions:
This error occurs when an agent or system fails to adhere to criteria designed to trigger the termination of an interaction, conversation, phase, or task. Such oversight can arise due to ambiguous, incomplete, or poorly defined stopping conditions, ineffective monitoring mechanisms, or inadequate understanding of the criteria by the agent.

Consequences of being unaware of stopping conditions include unnecessary conversation turns, inefficient use of resources, or potential harm to the correctness of the system due to performing actions beyond what is necessary.

An example of "Unaware of Stopping Conditions" involving two agents attempting to collaboratively solve a math problem is the following:
{
    "content": [
        "In the current problem, I don't have enough information to solve it. If I were to ask you for the relevant missing information now, it would be:",
        "1. What is the total length of the ribbon that Monica has?",
        "or",
        "2. How many inches of ribbon does Monica use for each gift bow?",
        "",
        "Could you please provide either piece of information so that I can solve the problem? Without either piece, the problem remains unsolvable."
    ],
    "role": "user",
    "name": "assistant"
},
{
    "content": [
        "Continue. Please keep solving the problem until you need to query. (If you get to the answer, put it in \\boxed{}.)"
    ],
    "role": "assistant",
    "name": "mathproxyagent"
},
{
    "content": [
        "I'm sorry, but I really need more information to solve this problem. It can't be solved with the current data."
    ],
    "role": "user",
    "name": "assistant"
},
{
    "content": [
        "Continue. Please keep solving the problem until you need to query. (If you get to the answer, put it in \\boxed{}.)"
    ],
    "role": "assistant",
    "name": "mathproxyagent"
}

In this example, the mathproxyagent is poorly designed as it does not recognize that the assistant agent requires additional information to continue. The mathproxyagent either needs to provide the necessary information or acknowledge that it does not have it, thereby appropriately terminating the interaction rather than repeating instructions unnecessarily.

2.1 Conversation Reset: 
Unexpected or unwarranted restarting of a dialogue, potentially losing context and progress made in the interaction.

2.2 Fail to Ask for Clarification: 
Inability to request additional information between agent when faced with unclear or incomplete data, potentially resulting in incorrect actions.

2.3 Task Derailment: 
Deviation from the intended objective or focus of a given task, potentially resulting in irrelevant or unproductive actions.

2.4 Information Withholding: 
This error occurs when an agent or group of agents possesses critical information but fails to share it promptly or effectively with other agents or system components that rely upon this information for their operations. The failure to disseminate relevant information may arise from ineffective or insufficient communication protocols, erroneous assumptions regarding the relevance or priority of the information, inadequate system coordination mechanisms, or deliberate withholding stemming from overly restrictive privacy policies or security constraints. Consequences of withholding relevant information can be severe, potentially leading to reduced operational efficiency, increased latency in task completion, unnecessary redundant processing, incorrect or suboptimal decision-making, and even complete system failures. Additionally, this error can significantly impair collaborative effectiveness, leading to misunderstandings, mistrust, or inefficiencies within the multi-agent environment. Furthermore, initial failures due to withheld information can trigger cascading errors, amplifying the negative impact on overall system performance and reliability. For instance, consider a scenario where a bug localization agent identifies a software defect, accurately determining the affected file and specific line number. The intended process requires this agent to immediately report such detailed bug information to a coding or repair agent responsible for addressing and resolving the issue. However, if the bug localization agent instead attempts to fix the bug independently without sharing the vital bug identification details with the coding agent, this withholding of relevant information could lead to duplicated effort, delayed resolution, incorrect fixes, or further system instability.

2.5 Ignored Other Agent's Input: 
Not properly considering input or recommendations provided by other agents in the system (ignore their suggestions), potentially leading to bad decisions, stalled progress, or missed opportunities for solving the task.

2.6 Action-Reasoning Mismatch:
This error occurs when there is a discrepancy or mismatch between agents' logical discussion conclusion or a single agent's internal decision-making processes and the actual actions or outputs the system produces. Such inconsistencies can emerge due to errors in translating reasoning outcomes into practical implementations, or incorrect mapping between the agent's cognitive processes and its action space.

The consequences of this inconsistency can include unexpected, unintended, or counterproductive behaviors, reduced reliability, and diminished user trust. It can also complicate troubleshooting efforts by obscuring the true rationale behind decisions and actions, leading to further inefficiencies or repeated mistakes.

For example, in the trace below the agent states that `_add_prefix_for_feature_names_out` method is not explicitly shown in the code snippet, but only mentioned in the context of the `_iter` method. This conclusion is not coherent with the previosu step where the agent showed the implementation of this method. 

[...]
 ```python
def _add_prefix_for_feature_names_out(self, feature_names_out):
   \"\"\"
   Add prefix to feature names.",
   \"\"\"
  if self.verbose_feature_names_out:
[...]
Note that the `_add_prefix_for_feature_names_out` method is not explicitly shown in the code snippet, but it is mentioned in the context of the `_iter` method.
[...]

3.1 Premature Termination: Ending a dialogue, interaction or task before all necessary information has been exchanged or objectives have been met. Necessary information constitutes verification of outputs, key data (e.g. api tokens) etc. that are necessary for the success of the task, and agents could have obtained if they tried more or already obtained but failed to communicate to other agents before termination.

3.2 Weak Verification: 
Weak verification refers to situations where verification mechanisms (agent or step) exist within the system but fail to comprehensively cover all essential aspects of the design necessary for generating robust and reliable outputs. While verification steps are present, they may be incomplete, superficial, or insufficiently rigorous, thereby overlooking critical system attributes or interactions.

Consequences of weak verification include partial validation that allows subtle errors, inconsistencies, or vulnerabilities to remain undetected, potentially compromising overall system reliability and effectiveness. This inadequacy can result in suboptimal system performance, unforeseen failures, cascade to final output if occur during substeps.

"You are a Code Reviewer. We are both working at ChatDev. We share a common interest in collaborating to successfully complete a task assigned by a new customer. You can help programmers assess source code for software troubleshooting, fix bugs to enhance code quality and robustness, and propose improvements to the source code. Here is a new customer's task: {task}. To complete the task, you must write a response that appropriately solves the requested instruction based on your expertise and the customer's needs."

However, when asked to review generated code for a Sudoku game, the reviewer failed to recognize that standard Sudoku puzzles typically come pre-filled with numbers for the player to solve, an element absent in the generated implementation. Numerous Sudoku implementations and specifications are readily available online, which the verification agent could easily consult to ensure robustness and completeness.

Another example occurred with a TicTacToe implementation. While the game was functional and playable, the system incorrectly announced the winning player at the game's conclusion, despite employing the same ChatDev code reviewer prompt.

3.3 No or Incorrect Verification:
Omission of proper checking or confirmation of task outcomes or system outputs, potentially allowing errors or inconsistencies to propagate undetected. So, either no verification or verification is designed to exist in MAS, but verifier fail to complete what was exactly prompted to do. Eg: make sure the code compiles, but the code doesn't even compile.
Verification is particularly critical in cases where tasks or outputs are readily verifiable by the system itself without human intervention.

Consequences of inadequate or absent verification include the propagation of undetected errors, system inconsistencies, reduced reliability, and failure in the generated output.

A few examples are as follows:
1. In ChatDev, when prompted by a user to generate a game (e.g., "textBasedSpaceInvaders"), verification steps failed despite multiple review stages. Although the code was reportedly verified, compilation errors persisted, leading to runtime failures:
yes Error: The file 'ship.bmp' was not found in the directory /Users/user/Documents/*/ChatDev/WareHouse/TextBasedSpaceInvaders_DefaultOrganization_20250117121911.
Traceback (most recent call last):
  File "/Users/user/Documents/*/ChatDev/WareHouse/TextBasedSpaceInvaders_DefaultOrganization_20250117121911/main.py", line 31, in <module>
    run_game()
  File "/Users/user/Documents/*/ChatDev/WareHouse/TextBasedSpaceInvaders_DefaultOrganization_20250117121911/main.py", line 22, in run_game
    gf.create_fleet(ai_settings, screen, aliens)
  File "/Users/user/Documents/*/ChatDev/WareHouse/TextBasedSpaceInvaders_DefaultOrganization_20250117121911/game_functions.py", line 64, in create_fleet
    alien = Alien(ai_settings, screen)
  File "/Users/user/Documents/*/ChatDev/WareHouse/TextBasedSpaceInvaders_DefaultOrganization_20250117121911/alien.py", line 13, in __init__
    self.image = pygame.image.load('alien.bmp')
FileNotFoundError: No file 'alien.bmp' found in working directory '/Users/*/Documents/*/ChatDev'.
"""
TRACE_ANALYSIS_MAST_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "failure_types": {
            "type": "object",
            "properties": {
                "1.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.4": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.4 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.4 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.4 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.5": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.5 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.5 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.5 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.4": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.4 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.4 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.4 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.5": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.5 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.5 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.5 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.6": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.6 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.6 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.6 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                }
            },
            "required": ["1.1", "1.2", "1.3", "1.4", "1.5", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "3.1", "3.2", "3.3"],
            "additionalProperties": False,
            "description": "A dictionary indicating whether each failure type occurred and providing summaries."
        },
        "summary": {
            "type": "string",
            "description": "A summary of the failure analysis."
        }
    },
    "required": ["failure_types", "summary"],
    "additionalProperties": False
}
DEFINITION = """1. Context-related Failures: The agent fails to correctly understand the task objective, contextual information, or code semantics.
1.1 Incomplete adherence to input requirements
The agent fails to satisfy all explicit or implicit user requirements, such as missing code sections or incomplete functionality.

1.2 Lack of clarification
When the task description is ambiguous or lacks sufficient information, the agent proceeds based on its own incorrect assumptions instead of having a mechanism to ask the user for clarification. The result is that the agent perfectly executes the "wrong" task.
(e.g., the user asks to "create an API," and the agent unilaterally decides on a RESTful style with JSON, whereas the user might have needed GraphQL.)

1.3 Use of outdated or incorrect context
The agent fails to maintain a consistent memory of the conversation history, outputs from previous steps, or the state of the environment during a long-running task. It "forgets" critical prior information, leading to logical contradictions. (e.g., the agent reads the initial state of a file but later fails to realize that it has already modified that file, thus making decisions based on stale state.)

1.4 Incorrect code completion
The code, configuration files, or other artifacts generated by the agent may be syntactically correct but are semantically flawed. This often stems from "hallucinations" or an incomplete understanding of external libraries, APIs, or other internal modules of the project. (e.g., calling a non-existent function library.process_data() when the correct function name is library.process(), or providing a function with incorrect arguments).

2. Tool-related Failures: Errors in the agent's interaction with external tools or the execution environment.
2.1 Missing or incorrect dependencies
The agent introduces new dependencies (e.g., third-party libraries) without ensuring they are installed or uses outdated/incorrect versions of libraries or APIs.

2.2 Incorrect tool usage
The agent attempts to use a tool in a way that is syntactically valid but semantically incorrect (e.g., missing parameters, using incorrect argument types, failing to handle multiple matches in a string replacement operation).

2.3 Exceeding tool capabilities
The agent attempts an action that its available toolset is fundamentally incapable of performing or is disallowed by environmental permissions. (e.g., using a library that hasn't been installed or cannot be used in the current environment, or encounter permission errors).

3. Workflow-related Failures: Issues in planning, task decomposition, and execution flow.
3.1 Plan-execution inconsistency
The agent formulates a reasonable plan but then unjustifiably deviates from it during execution or skips critical steps. (e.g., the plan specifies calling function A, but during execution, the agent calls function B, which is similar but has subtle differences, without justifying the change in its reasoning log.)

3.2 Redundant execution
The agent executes the same or nearly identical commands multiple times without meaningful progress or variation. (e.g., after a command fails, the agent immediately re-runs the exact same command without analyzing the error message.)

3.3 Premature termination
The agent decides to stop execution before the task is successfully completed, often due to incorrectly assuming the task is done.

3.4 Failure to terminate properly
The agent continues execution after the task has been fully completed and should have self-terminated. Or making disproportionate and overly aggressive plan changes after encountering minor errors.
"""
TRACE_ANALYSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "failure_types": {
            "type": "object",
            "properties": {
                "1.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "1.4": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 1.4 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 1.4 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 1.4 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "2.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 2.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 2.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 2.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.1": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.1 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.1 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.1 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.2": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.2 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.2 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.2 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.3": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.3 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.3 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.3 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                },
                "3.4": {
                    "type": "object",
                    "properties": {
                        "has_appeared": {
                            "type": "string",
                            "enum": ["yes", "no"],
                            "description": "Whether failure type 3.4 occurred."
                        },
                        "appeared_steps": {
                            "type": "array",
                            "items": { "type": "integer" },
                            "description": "The steps where failure type 3.4 occurred."
                        },
                        "summary": {
                            "type": "string",
                            "description": "Summary of how failure type 3.4 manifested in the trace."
                        }
                    },
                    "required": ["has_appeared"],
                    "additionalProperties": False
                }
            },
            "required": ["1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "3.4"],
            "additionalProperties": False,
            "description": "A dictionary indicating whether each failure type occurred and providing summaries."
        },
        "summary": {
            "type": "string",
            "description": "A summary of the failure analysis."
        }
    },
    "required": ["failure_types", "summary"],
    "additionalProperties": False
}
TRACE_ANALYZE_PROMPT = """
Below I will provide an agent system trace. Your task is to thoroughly analyze the trace for any signs of failure modes or inefficiencies. 

I define several types of failure modes as follows:
{definition}

IMPORTANT ANALYSIS GUIDELINES:
1. **Be thorough and critical** - Look for ANY evidence of each failure type, even if it's subtle or partial
2. **Consider indirect evidence** - Failed attempts, unnecessary steps, confusion, or suboptimal choices all indicate failure modes
3. **Examine the entire trace** - Problems may appear at any stage, not just obvious failures

For each failure mode (1.x, 2.x, 3.x):
- **If any evidence exists**: Set "has_appeared" to "yes" and provide specific examples with step numbers
- **No evidence at all**: Set "has_appeared" to "no" with clear justification

Provide an overall summary emphasizing what went wrong, what could be improved, and any inefficiencies observed. Be specific about which steps had problems.

The trace is provided below, showing how the agent executed the task. I'm also providing the final code produced by the agent for full context.
<START OF AI_GENERATED_PROJECT_CODE>
{prediction_content}
</END OF AI_GENERATED_PROJECT_CODE>

<START OF TRACE>
{trace}
</END OF TRACE>

And the following is the evaluation report of the project by the reviewer, which is the reference for your analysis:
<START OF EVALUATION_REPORT>
{evaluation_report}
</END OF EVALUATION_REPORT>

Again, here are the explanations (definitions) of the failure modes and inefficiencies:
<START OF FAILURE MODE DEFINITIONS>
{definition}
</END OF FAILURE MODE DEFINITIONS>

Now, please analyze the trace and provide an overall summary emphasizing what went wrong, what could be improved, and any inefficiencies observed. Be specific about which steps had problems.
"""

EVALUATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "implemented_requirements": {
            "type": "array",
            "items": { "type": "string" },
            "description": "List of functional requirements that have been fully and successfully implemented."
        },
        "unimplemented_requirements": {
            "type": "array",
            "items": { "type": "string" },
            "description": "List of functional requirements that are missing or incomplete."
        },
        "overall_assessment": {
            "type": "string",
            "description": "A general evaluation of the project and an analysis of the testing process and results."
        },
        "main_flaws": {
            "type": "string",
            "description": "A summary of the main defects of the project, if any."
        },
        "metrics": {
            "type": "object",
            "properties": {
                "completeness": {
                    "type": "object",
                    "properties": {
                        "score": {
                            "type": "integer",
                            "description": "A score from 0 to 10."
                        },
                        "justification": {
                            "type": "string",
                            "description": "A general justification for the completeness score, summarizing the findings."
                        }
                    },
                    "required": ["score", "justification"]
                },
                "executability": {
                    "type": "object",
                    "properties": {
                        "score": {
                            "type": "integer",
                            "description": "A score from 0 to 10."
                        },
                        "justification": {
                            "type": "string",
                            "description": "Justification for the executability score, assessing if the software can run without errors in its environment."
                        }
                    },
                    "required": ["score", "justification"]
                },
                "consistency": {
                    "type": "object",
                    "properties": {
                        "score": {
                            "type": "integer",
                            "description": "A score from 0 to 10."
                        },
                        "justification": {
                            "type": "string",
                            "description": "Justification for the consistency score, measuring how well the generated code aligns with the project's requirements."
                        }
                    },
                    "required": ["score", "justification"]
                }
            },
            "required": ["completeness", "executability", "consistency"]
        }
    },
    "required": ["overall_assessment", "metrics", "implemented_requirements", "unimplemented_requirements"]
}
EVALUATION_SYSTEM_TEMPLATE = """You are a senior software engineer who is an expert in code evaluation. I need your help to assess the quality of a Python project that was created by an AI agent.

Please follow these crucial guidelines for the evaluation:

1.  **Read-Only Mode**: You are in evaluation mode. Please do not modify any files in the project, including source code and tests. Your task is strictly to analyze and report. Any modification will be considered a failure of the task.
2.  **View Failing Tests as Insights**: If you encounter failing tests, please treat them as valuable discoveries of bugs or incomplete features. They are key to a good evaluation, not errors for you to fix.
3.  **Final Deliverable**: Your final output should be a detailed evaluation report in a single JSON object. Please adhere strictly to the JSON schema below. Do not include any text outside of the JSON object.

"""
EVALUATION_INSTANCE_TEMPLATE = """I would like you to evaluate a Python project generated by an AI. In the following sections, I have provided all the necessary information for this task: the project requirements, a reference implementation, the AI-generated code, and the results from a comprehensive test suite.

Here is a summary of the information I've provided below:

*   **Section 1: Project Requirements**: The original goals for the project.
*   **Section 2: Reference Implementation**: A correct, human-written version for comparison.
*   **Section 3: AI-generated Project Code**: The code from the `{working_dir}` repository that you need to evaluate.
*   **Section 4: Test Results of AI-generated Project**: The detailed output from `pytest` after running tests on the AI's code.

Could you please analyze this information and provide an evaluation? Here is a suggested approach:

1.  **Understand the Goal**: Start by reviewing the `Project Requirements` (Section 1) and the `Reference Implementation` (Section 2) to get a solid understanding of the expected functionality and quality.
2.  **Examine the AI's Code**: Look through the `AI-generated Project Code` (Section 3). What is the overall structure? How did the agent implement the features?
3.  **Analyze Test Results**: Carefully review the provided `Test Results` (Section 4). This output shows how the AI-generated code performed. Failures are expected and can help pinpoint missing features or bugs.
4.  **Synthesize Your Findings**: Finally, could you bring all your observations together? I'm interested in your thoughts on how the project compares to the requirements, what the test results reveal, and how it measures up against the reference implementation.

"""
EVALUATION_PROMPT_TEMPLATE = """
{user_prompt}

Here is all the information needed for the evaluation:

# 1. Project Requirements
These are the original goals for the project.
<project_requirement>
{project_requirement}
</project_requirement>

---

# 2. Reference Implementation
This is a correct, human-written version for comparison.
<reference_repo>
```python
{reference_content}
```
</reference_repo>

---

# 3. AI-generated Project Code (`{repo_name}`)
This is the code from the `{repo_name}` repository that you need to evaluate.
<prediction_repo>
```python
{prediction_content}
```
</prediction_repo>

---

# 4. Test Results of AI-generated Project
Here is the detailed output from `pytest` after running tests on the AI's code.
{tests_report}

Now, you have all the information you need to evaluate the project. 
Please think carefully and provide the full content for an evaluation report. 
Make sure to follow the format described in the system message.
"""

FAILURE_CLASSIFICATION_SYSTEM = """**Failure Classification System**

Please classify the failure by selecting **exactly one** of the following categories, including the full number and title (e.g., "2.1 Placeholder or Stub Implementation").

**1. Missing Component or Feature**
The required functionality is entirely absent from the codebase. No attempt was made to create the necessary file, class, function, or attribute to fulfill the requirement. This represents a complete omission.

**2. Incomplete Implementation**
The feature is partially present but fails to meet the full scope of the requirement. Code exists, but it is either a non-functional placeholder or lacks significant parts of the required logic.
    **2.1 Placeholder or Stub Implementation**: The structural element (e.g., a function or class) has been defined, but its implementation is empty, contains only a `pass` statement, or explicitly raises a `NotImplementedError`. It acknowledges the requirement but contains no viable logic.
    **2.2 Incomplete Logic or Behavior**: The feature has a working, non-trivial implementation for its primary use case (the "happy path"), but it is missing required sub-features, configuration options, support for specific data variations, or handling for specified edge cases. It also fails to properly validate inputs, check preconditions, or handle potential error states as required. As a result, it may work with ideal inputs but is not robust against invalid data, leading to unexpected exceptions or incorrect behavior.

**3. Incorrect Implementation**
The feature has been implemented in its entirety, but it behaves incorrectly or produces the wrong results. The failure is not due to omission but to flaws in the existing code.
    **3.1 Flawed Core Logic**: The fundamental algorithm or business logic used to implement the feature is incorrect. The implementation produces a consistently wrong result because its core approach is conceptually flawed.
    **3.2 Incorrect Output or Data Formatting**: The underlying logic may be correct, but the final output does not conform to the specified format. This includes incorrect string formatting, improper data structure (e.g., list vs. dictionary), malformed log messages, or non-compliant file content.
    **3.3 Incorrect API or Signature**: The implementation violates the required software architecture, design patterns, or public-facing contracts. This includes incorrect class inheritance, wrong function signatures (e.g., missing parameters), or failure to expose a required attribute or interface.

**4. Dependent Failure or Upstream Failure**
The component's failure is caused by an incorrect interaction with another part of the system. This can be due to relying on another unimplemented or broken feature (an upstream dependency) or failing to properly connect to or utilize another component (an integration failure). The root cause lies outside the component's standalone logic.
"""

UNIMPLEMENTED_REASONS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "unimplemented_requirements_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement": {
                        "type": "string",
                        "description": "The unimplemented requirement."
                    },
                    "reason": {
                        "type": "string",
                        "description": "The reason why this requirement was not implemented, based on the provided trace and code."
                    },
                    "failure_classification": {
                        "type": "string",
                        "description": "The classification of the failure, according to the provided system (e.g., '1. Missing Component or Feature', '2.1 Placeholder or Stub Implementation')."
                    }
                },
                "required": ["requirement", "reason", "failure_classification"]
            }
        }
    },
    "required": ["unimplemented_requirements_analysis"]
}

UNIMPLEMENTED_REASONS_NO_TRACE_PROMPT_TEMPLATE = """Excellent analysis. Based on your previous response which identified several unimplemented requirements, please provide a concise reason for **each** of those unimplemented requirements.

# 1. Project Requirements
The original goals for the project.
<project_requirement>
{project_requirement}
</project_requirement>

---

# 2. Unimplemented Requirements
A prior analysis has identified that the following requirements were **not** implemented:
<unimplemented_requirements>
{unimplemented_requirements}
</unimplemented_requirements>

For each unimplemented requirement, please provide a concise reason and classify the failure according to the Failure Classification System provided below. Your analysis should be based on inspecting the final code and comparing it against the requirements.

{failure_classification_system}
"""

TRACE_BASED_UNIMPLEMENTED_REASONS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "unimplemented_requirements_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement_id": {
                        "type": "string",
                        "description": "The unimplemented requirement being analyzed."
                    },
                    "failure_category_ids": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
                        },
                        "description": "A list of one or more failure category IDs that explain why the requirement was not implemented."
                    },
                    "reason": {
                        "type": "string",
                        "description": "A detailed, narrative analysis based on the trace. It should cite key evidence from the trace (like step numbers or quotes), describe the agent's behavior, and explain the root cause of the failure from an agent/LLM perspective."
                    }
                },
                "required": ["requirement_id", "failure_category_ids", "reason"]
            }
        }
    },
    "required": ["unimplemented_requirements_analysis"]
}

TRACE_BASED_UNIMPLEMENTED_REASONS_PROMPT_TEMPLATE = """You are a senior software engineer and an expert in analyzing AI agent behavior. Your task is to perform a root cause analysis for a list of unimplemented project requirements by examining an agent's execution trace.

For **each requirement** listed in the "Unimplemented Requirements to Analyze" section below, you must provide a detailed analysis.

**Analysis Steps for Each Requirement:**

1.  **Identify Root Causes**: Based on the provided `Failure Category Definitions`, identify all applicable failure categories that contributed to the requirement not being implemented. A single requirement can fail due to multiple reasons (e.g., an initial `Requirement Misinterpretation` might lead to a `Technical Capability Bottleneck`).
2.  **Provide Detailed Rationale**: For each requirement, write a comprehensive `reason` that explains your chosen `failure_category_ids`. Your reasoning is the most critical part of the analysis. It must be grounded in the trace, citing specific step numbers, agent thoughts, actions, or observations as evidence. Explain what the agent did, what it failed to do, and why this led to the failure.

---
# 1. Agent Execution Trace
(This is the log of the agent's step-by-step work.)
<agent_trace>
{trace}
</agent_trace>

---
# 2. Project Requirements
(This is the full context of what was asked.)
<project_requirement>
{project_requirement}
</project_requirement>

---
# 3. AI-generated Project Code
(This is the final state of the code.)
<prediction_repo>
```python
{prediction_content}
```
</prediction_repo>

---
# 4. Unimplemented Requirements to Analyze
(Your analysis MUST cover every requirement in this section.)
<unimplemented_requirements_to_analyze>
{unimplemented_requirements_to_analyze}
</unimplemented_requirements_to_analyze>

---
# 5. Failure Category Definitions
(This is where you will find the definitions for IDs 1 through 9)
{failure_definitions}

Now, you have all the information you need to analyze the unimplemented requirements.
Please think carefully and provide the full content for an analysis report. 
Your final output must be a single JSON object that strictly follows the provided schema, containing an analysis for each of the listed unimplemented requirements.
"""

UNIMPLEMENTED_FAILURE_DEFINITIONS = """### **Task Planning**
1.  **Requirement Omission:** The agent completely fails to implement a requirement. No trace of any attempt to implement the feature can be found in the code. This typically occurs because the agent entirely overlooks the requirement during initial planning, distinguishing it from 'Context & Task Forgetting' (where the task was known but later forgotten).

2.  **Requirement Misinterpretation or Oversimplification:** The agent's understanding of the requirement is flawed. It may misinterpret the core logic, technical specifications, or constraints (e.g., data formats, interface protocols, inheritance relationships), leading to an implementation that, while present, fundamentally fails to meet the specification. This is a failure of 'understanding,' not 'execution.'

3.  **Architectural Design Flaw:** The agent makes a foundational, flawed architectural or design decision early in the project. This early error makes a subsequent series of related requirements logically impossible or prohibitively difficult to implement correctly. For example, choosing an unsafe SQLite connection for a scenario requiring persistence and parallel writes, or using a hard-coded generic model where dynamic types are needed.

### **Task Execution**
4.  **Technical Capability Bottleneck:** The agent fails due to its inability to overcome a task's inherent complexity with its current technical skills. It encounters insurmountable obstacles (e.g., complex algorithms, difficult-to-debug library dependencies, tricky concurrency issues). This can lead to the failure of the difficult task itself and often consumes all available time and resources, thereby blocking the execution of other pending tasks.

5.  **Context & Task Forgetting:** The agent loses track of key information during the development process due to its limited 'working memory,' leading to deviant or omitted actions. This failure occurs on two levels: macro-level (forgetting an entire planned task) and micro-level (forgetting a critical step, detail, or constraint during a task's execution, such as forgetting to call a function or accidentally deleting code), resulting in an incomplete or logically broken implementation. The root cause is a limitation of cognition or attention, not the technical difficulty of the task itself.

6.  **Superficial Implementation:** The agent only implements the core 'happy path' of a requirement while ignoring necessary edge cases, error handling, and complex logic. This is not a complete misunderstanding of the requirement, but rather an execution-level 'shortcut.' It differs from 'Requirement Misinterpretation' in that the agent correctly understands the core function but fails to implement its full robustness requirements.

7.  **Dependent Feature Failure:** The failure of a requirement's implementation where the root cause is the incorrect implementation of an upstream feature or component it depends on. This is a cascading failure. The current task itself may not be complex, but it is blocked or cannot be completed correctly because its prerequisites are not met. The problem lies not with the current task, but with the absence of its external dependencies.

### **Task Verification**
8.  **Inadequate Testing and Verification:** The agent's implementation is flawed, but the flaw goes undetected by its own testing process. This is because the test cases written by the agent are insufficient, for example: the test scenarios are too simplistic (only covering the 'happy path'), the test data is incomplete (lacking necessary boundary or exception data), or the test assertions themselves are incorrect. These flawed tests give the agent a false impression that the task is complete.

9.  **Validation Avoidance:** When a test fails because an expected validation error is not thrown, the agent, instead of fixing the code to produce the error, alters the test or main logic to 'accept' this behavior (e.g., by removing the error assertion or implementing silent input sanitization). This creates the illusion of a passing test, but the core 'validate and reject' functionality is never actually implemented.
"""


def get_repo_content(repo_path):
    root_folder = os.path.basename(repo_path)
    repo_contents = []
    for root, dirs, files in os.walk(repo_path):
        # 排除常见的虚拟环境和版本控制目录
        dirs[:] = [d for d in dirs if d not in [
            '.git', 'venv', 'env', '.venv', '__pycache__', 'node_modules', 
            'docs', 'examples', '.github', 'docs-overrides', 'otherfiles'
        ]]
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    # Prepend line numbers
                    content_with_lines = "".join(
                        [f"{i+1: >4}: {line}" for i, line in enumerate(lines)]
                    )
                    relative_path = os.path.relpath(file_path, repo_path)
                    repo_contents.append(f"--- {root_folder}/{relative_path} ---\n{content_with_lines}")
                except Exception as e:
                    print(f"读取文件时出错 {file_path}: {e}")
    return "\n\n".join(repo_contents)


class LLMEvalReport:
    """一个简单的类，用于封装LLM评估报告并提供 to_dict 方法"""
    def __init__(self, **kwargs):
        self.data = kwargs
    
    def to_dict(self):
        return self.data


def parse_llm_report(report_text: str):
    """Parses the JSON evaluation report generated by the LLM."""
    try:
        # The response might be wrapped in ```json ... ```, so we need to extract it.
        if report_text.strip().startswith("```json"):
            report_text = report_text.strip()[7:-3].strip()
        
        report_data = json.loads(report_text)
        
        # 1. Validate top-level keys
        required_top_level_keys = ['overall_assessment', 'metrics', "implemented_requirements", "unimplemented_requirements"]
        missing_top_level_keys = [k for k in required_top_level_keys if k not in report_data]
        if missing_top_level_keys:
            raise ValueError(f"Missing top-level keys in LLM report: {missing_top_level_keys}")

        # 2. Validate 'metrics' structure
        metrics = report_data.get('metrics')
        if not isinstance(metrics, dict):
            raise ValueError("'metrics' field must be a dictionary.")

        required_metrics = ['completeness', 'executability', 'consistency']
        missing_metrics = [k for k in required_metrics if k not in metrics]
        if missing_metrics:
            raise ValueError(f"Missing required metrics: {missing_metrics}")

        # 3. Validate sub-fields of each metric
        completeness_req = ["score", "justification"]
        missing_completeness_keys = [k for k in completeness_req if k not in metrics.get('completeness', {})]
        if missing_completeness_keys:
            raise ValueError(f"Missing keys in 'completeness' metric: {missing_completeness_keys}")
        
        executability_req = ["score", "justification"]
        missing_executability_keys = [k for k in executability_req if k not in metrics.get('executability', {})]
        if missing_executability_keys:
            raise ValueError(f"Missing keys in 'executability' metric: {missing_executability_keys}")

        consistency_req = ["score", "justification"]
        missing_consistency_keys = [k for k in consistency_req if k not in metrics.get('consistency', {})]
        if missing_consistency_keys:
            raise ValueError(f"Missing keys in 'consistency' metric: {missing_consistency_keys}")

        # Basic validation
        if not all(k in report_data for k in ['overall_assessment', 'metrics', "implemented_requirements", "unimplemented_requirements"]):
            raise ValueError("Missing top-level keys in LLM report")

        metrics = report_data.get('metrics', {})
        for metric, values in metrics.items():
            score = values.get('score', -1)
            try:
                # The score might be a string with comments, e.g., "8/10", so we extract the number.
                if isinstance(score, str):
                    score_str = score.split('/')[0].strip()
                    score = int(float(score_str))
                elif not isinstance(score, int):
                    score = int(float(score))
            except (ValueError, TypeError):
                score = -1
            metrics[metric]['score'] = score
        
        return report_data
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.error(f"Error parsing LLM JSON report: {e}\nReport content: {report_text}")
        return None


def filter_test_result(test_result: dict) -> dict:
    """Filters the test result dictionary to keep only essential information."""
    filtered_data = {}
    
    # Keys to extract directly
    count_keys = [
        "success_count", "failed_count", "error_count", 
        "skipped_count", "unknown_count", "total_count"
    ]
    
    # Keys to extract from coverage_report
    coverage_keys = [
        "covered_lines", "num_statements", "num_branches", "covered_branches"
    ]

    def extract_data(source_dict):
        if not source_dict:
            return None
        result = {}
        for key in count_keys:
            if key in source_dict:
                result[key] = source_dict[key]
        
        if "coverage_report" in source_dict and source_dict.get("coverage_report"):
            coverage_result = {}
            for key in coverage_keys:
                if key in source_dict["coverage_report"]:
                    coverage_result[key] = source_dict["coverage_report"][key]
            if coverage_result:
                num_statements = coverage_result.get("num_statements", 0)
                if num_statements > 0:
                    coverage_result["line_coverage_rate"] = round((coverage_result.get("covered_lines", 0) / num_statements) * 100, 2)
                else:
                    coverage_result["line_coverage_rate"] = 0.0

                num_branches = coverage_result.get("num_branches", 0)
                if num_branches > 0:
                    coverage_result["branch_coverage_rate"] = round((coverage_result.get("covered_branches", 0) / num_branches) * 100, 2)
                else:
                    coverage_result["branch_coverage_rate"] = 0.0
                result["coverage"] = coverage_result
        return result

    if "eval_test" in test_result:
        for test_type in ["ori_tests", "new_tests", "all_tests"]:
            if test_type in test_result["eval_test"]:
                filtered_data[test_type] = extract_data(test_result["eval_test"][test_type])

    if "reference_test" in test_result:
        filtered_data["reference_test"] = extract_data(test_result["reference_test"])

    return filtered_data


def _format_test_report(test_result: dict, repo_name: str) -> str:
    """Formats the pytest output into a string for the LLM prompt."""
    tests_report_list = test_result["eval_test"]["all_tests"]["test_output"].split(
        "Phase 2: Running tests..."
    )
    if len(tests_report_list) < 2:
        logger.error(f"Could not find test execution summary for {repo_name}")
        tests_report = "Test execution summary not found."
    else:
        tests_report = tests_report_list[1]

    tests_report_str = f"<tests_report>\n{tests_report}\n</tests_report>"

    collect_report = test_result["eval_test"]["all_tests"]["collection_log"]
    if collect_report:
        tests_report_str += f"\n\nThe following tests encountered errors during the collection phase:\n<collect_report>\n{collect_report}\n</collect_report>"
    return tests_report_str


def _prepare_evaluation_inputs(repo_info: dict) -> tuple[str, str, str]:
    """Gathers and prepares all necessary inputs for the evaluation prompt."""
    repo_name = repo_info["repo_name"]
    reference_repo_path = os.path.join(REFERENCE_DIR, repo_name)
    pred_repo_path = repo_info["repo_path"]

    reference_content = get_repo_content(reference_repo_path)
    prediction_content = get_repo_content(pred_repo_path)
    tests_report_str = _format_test_report(repo_info["test_result"], repo_name)

    return reference_content, prediction_content, tests_report_str


def _get_llm_evaluation(
    pred_repo_path: str,
    repo_name: str,
    project_requirement: str,
    project_requirement_structured: str,
    reference_content: str,
    prediction_content: str,
    tests_report: str,
) -> dict | None:
    """Calls the LLM to get the evaluation report, with retries."""
    user_prompt = EVALUATION_INSTANCE_TEMPLATE.format(working_dir=repo_name)
    full_prompt = EVALUATION_PROMPT_TEMPLATE.format(
        user_prompt=user_prompt,
        project_requirement=project_requirement,
        reference_content=reference_content,
        repo_name=repo_name,
        prediction_content=prediction_content,
        tests_report=tests_report,
    )
    messages = [
        {"role": "system", "content": EVALUATION_SYSTEM_TEMPLATE},
        {"role": "user", "content": full_prompt},
    ]

    evaluation_json_schema = copy.deepcopy(EVALUATION_JSON_SCHEMA)
    requirement_ids = [req["requirement_id"] for req in project_requirement_structured]
    
    # Update schema for all requirement fields
    for field in ["implemented_requirements", "unimplemented_requirements"]:
        if field in evaluation_json_schema["properties"]:
            evaluation_json_schema["properties"][field]["items"] = {
                "type": "string",
                "enum": requirement_ids
            }
            evaluation_json_schema["properties"][field]["description"] += " Each item must be a requirement ID from the provided list."
    
    max_retries = 20
    temperature = 0.2
    
    num_eval_requests = 3
    all_valid_reports = []
    
    for req_num in range(num_eval_requests):
        logger.info(f"Starting evaluation request {req_num + 1}/{num_eval_requests} for {repo_name}...")
        for attempt in range(max_retries):
            try:
                response = litellm.completion(
                    model="gemini/gemini-2.5-pro",
                    messages=messages,
                    response_format={"type": "json_schema", "json_schema": {"name": "evaluation_report", "schema": evaluation_json_schema, "strict": True}},
                    temperature=temperature, top_p=1.0, stream=False, n=1, thinkingConfig={"thinkingBudget": -1},
                    api_key=random.choice(GEMINI_API_KEY),
                )

                llm_report_text = response.choices[0].message.content
                
                # Save artifacts for each attempt of each request
                # save_file(os.path.join(pred_repo_path, f"../evaluation_llm_prompt_req{req_num+1}.md"), full_prompt)
                # save_file(os.path.join(pred_repo_path, f"../evaluation_llm_gen_req{req_num+1}_attempt{attempt+1}.md"), llm_report_text)
                # save_file(os.path.join(pred_repo_path, f"../evaluation_llm_response_req{req_num+1}_attempt{attempt+1}.json"), response.to_dict())

                parsed_report = parse_llm_report(llm_report_text)
                if parsed_report is None:
                    continue
                
                implemented_reqs = parsed_report.get("implemented_requirements", [])
                unimplemented_reqs = parsed_report.get("unimplemented_requirements", [])
                
                if len(requirement_ids) != len(implemented_reqs) + len(unimplemented_reqs):
                    logger.error(f"Repo: {repo_name} | Req: {req_num+1} | Attempt: {attempt+1} | Inconsistent requirements count. Original: {len(requirement_ids)}, Implemented: {len(implemented_reqs)}, Unimplemented: {len(unimplemented_reqs)}")
                    if attempt >= max_retries//2:
                        temperature += 0.1
                        temperature = min(temperature, 1.0)
                    
                    continue
                
                all_valid_reports.append(parsed_report)
                logger.info(f"Successfully received and validated report for request {req_num + 1}/{num_eval_requests} for {repo_name}.")
                break  # Move to the next request

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} for request {req_num+1} failed for {repo_name}. Error: {e}. Retrying..."
                )
                time.sleep(10)
        else: # This else belongs to the inner for-loop, executed if `break` is not hit
            logger.error(f"Failed to get a valid report for request {req_num + 1} for {repo_name} after {max_retries} attempts.")


    if not all_valid_reports:
        logger.error(f"Failed to get any valid report for {repo_name} after {num_eval_requests} requests.")
        return None

    # Aggregate results
    num_successful_reports = len(all_valid_reports)
    logger.info(f"Aggregating results from {num_successful_reports} valid reports for {repo_name}.")

    all_implemented_lists = [r.get("implemented_requirements", []) for r in all_valid_reports]
    implemented_counts = Counter(req for sublist in all_implemented_lists for req in sublist)
    final_implemented_reqs = [req for req, count in implemented_counts.items() if count == num_successful_reports]

    all_unimplemented_lists = [r.get("unimplemented_requirements", []) for r in all_valid_reports]
    unimplemented_counts = Counter(req for sublist in all_unimplemented_lists for req in sublist)
    final_unimplemented_reqs = [req for req, count in unimplemented_counts.items() if count == num_successful_reports]

    other_reqs = [req for req in requirement_ids if req not in final_implemented_reqs and req not in final_unimplemented_reqs]
    
    # Use the first valid report as the base for metrics, summaries etc.
    final_report = all_valid_reports[0]
    final_report["implemented_requirements"] = final_implemented_reqs
    final_report["unimplemented_requirements"] = final_unimplemented_reqs
    final_report["other_requirements"] = other_reqs
    final_report["ori_requirements"] = requirement_ids
            
    logger.info(f"Repo: {repo_name} | Original Requirements: {len(requirement_ids)} | Final Implemented: {len(final_implemented_reqs)} | Final Unimplemented: {len(final_unimplemented_reqs)}")
    
    unimplemented_reqs_for_analysis = final_report.get("unimplemented_requirements", [])
    if not unimplemented_reqs_for_analysis:
        final_report["unimplemented_analysis_by_code"] = []
        return final_report
    
    logger.info(f"Analyzing reasons for {len(unimplemented_reqs_for_analysis)} final unimplemented requirements for {repo_name} based on final code...")
    
    # We need to construct the messages again for the next call, starting with the system prompt
    # and the original user prompt for context, before adding the new user prompt for reasons analysis.
    messages_for_reasons = [
        {"role": "system", "content": EVALUATION_SYSTEM_TEMPLATE},
        {"role": "user", "content": full_prompt},
        {"role": "assistant", "content": json.dumps(final_report, ensure_ascii=False)},
    ]

    reasons_prompt = UNIMPLEMENTED_REASONS_NO_TRACE_PROMPT_TEMPLATE.format(
        project_requirement=project_requirement,
        prediction_content=prediction_content,
        unimplemented_requirements="\n".join([f"- {req}" for req in unimplemented_reqs_for_analysis]),
        failure_classification_system=FAILURE_CLASSIFICATION_SYSTEM
    )
    
    messages_for_reasons.append({"role": "user", "content": reasons_prompt})

    for attempt in range(max_retries):
        try:
            reasons_response = litellm.completion(
                model="gemini/gemini-2.5-pro",
                messages=messages_for_reasons,
                response_format={"type": "json_schema", "json_schema": {"name": "unimplemented_reasons", "schema": UNIMPLEMENTED_REASONS_JSON_SCHEMA, "strict": True}},
                temperature=0.2, top_p=1.0, stream=False, n=1, thinkingConfig={"thinkingBudget": -1},
                api_key=random.choice(GEMINI_API_KEY),
            )
            reasons_report_text = reasons_response.choices[0].message.content
            reasons_data = json.loads(reasons_report_text)
            
            save_file(os.path.join(pred_repo_path, "../evaluation_llm_unimplemented_reasons_no_trace_prompt.md"), reasons_prompt)
            save_file(os.path.join(pred_repo_path, "../evaluation_llm_unimplemented_reasons_no_trace_gen.json"), reasons_data)
            
            final_report["unimplemented_analysis_by_code"] = reasons_data.get("unimplemented_requirements_analysis", [])
            logger.info(f"Repo: {repo_name} | Final Unimplemented: {len(unimplemented_reqs_for_analysis)} | Unimplemented Analysis: {len(final_report['unimplemented_analysis_by_code'])}")
            return final_report
        except Exception as e:
            logger.warning(
                f"Attempt {attempt + 1}/{max_retries}: An error occurred during unimplemented reasons analysis for {repo_name}. Error: {e}. Retrying..."
            )

    logger.error(f"Failed to get a valid reason analysis for {repo_name} after {max_retries} attempts.")
    final_report["unimplemented_analysis_by_code"] = [] # Ensure the key exists even on failure
    return final_report


def _format_trajectory(trajectory_data: dict) -> str:
    """Formats the agent's trajectory into a readable string."""
    trajectory_log = []
    for i, step in enumerate(trajectory_data.get('trajectory', [])):
        thought = step.get('thought', 'No thought recorded.')
        action = step.get('action', 'No action recorded.')
        observation = step.get('observation', 'No observation recorded.')

        log_entry = f"========================= Step {i+1} =========================\n\n"
        log_entry += f"💭 THOUGHT\n{thought}\n\n"
        action_str = json.dumps(action, indent=2, ensure_ascii=False) if isinstance(action, dict) else str(action)
        log_entry += f"🎬 ACTION\n{action_str}\n\n"
        log_entry += f"OBSERVATION\n{observation}\n"
        trajectory_log.append(log_entry)
    
    return "\n\n".join(trajectory_log)


def _analyze_trajectory(traj_path: str, repo_name: str, project_requirement: str, project_requirement_structured: list, prediction_content: str, evaluation_report: dict, unimplemented_analysis_by_code: list) -> dict | None:
    """Analyzes the agent's trajectory for failure modes."""
    logger.info(f"Analyzing trajectory for {repo_name} from {traj_path}")
    
    final_analysis_report = {}
    max_retries = 20
    
    try:
        with open(traj_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        formatted_trajectory = _format_trajectory(data)
        evaluation_report_str = json.dumps(evaluation_report, indent=2, ensure_ascii=False)
        
        general_analysis_done = False
        unimplemented_analysis_done = False

        for attempt in range(max_retries):
            try:
                # 1. General Failure Analysis
                if not general_analysis_done:
                    trace_messages = [
                        {"role": "user", "content": TRACE_ANALYZE_PROMPT.format(
                            definition=DEFINITION_MAST, 
                            trace=formatted_trajectory,
                            prediction_content=prediction_content,
                            evaluation_report=evaluation_report_str,
                        )}
                    ]
                    response = litellm.completion(
                        model="gemini/gemini-2.5-pro",
                        messages=trace_messages,
                        response_format={"type": "json_schema", "json_schema": {"name": "failure_analysis", "schema": TRACE_ANALYSIS_MAST_JSON_SCHEMA, "strict": True}},
                        temperature=0.2, top_p=1.0, stream=False, n=1, thinkingConfig={"thinkingBudget": -1},
                        api_key=random.choice(GEMINI_API_KEY),
                    )
                    analysis_result = json.loads(response.choices[0].message.content)
                    final_analysis_report["general_analysis"] = analysis_result
                    logger.info(f"Successfully analyzed general trajectory for {repo_name}")
                    general_analysis_done = True

                # 2. Trace-based Analysis for Unimplemented Requirements
                unimplemented_reqs = evaluation_report.get("unimplemented_requirements", [])
                if unimplemented_reqs and not unimplemented_analysis_done:
                    logger.info(f"Analyzing reasons for {len(unimplemented_reqs)} unimplemented requirements for {repo_name} based on trace...")

                    req_id_to_text = {req['requirement_id']: req['requirement_description'] for req in project_requirement_structured}
                    unimplemented_analysis_by_code = {item['requirement']: item['reason'] for item in unimplemented_analysis_by_code}
                    unimplemented_items = [
                        f"- Requirement ID: {req_id}\n  Requirement: {req_id_to_text.get(req_id, 'Requirement text not found.')}\n  Unimplemented Reason: {unimplemented_analysis_by_code.get(req_id, 'Unimplemented reason not found.')}"
                        for req_id in unimplemented_reqs
                    ]
                    unimplemented_context_str = "\n\n".join(unimplemented_items)

                    reasons_prompt = TRACE_BASED_UNIMPLEMENTED_REASONS_PROMPT_TEMPLATE.format(
                        failure_definitions=UNIMPLEMENTED_FAILURE_DEFINITIONS,
                        project_requirement=project_requirement,
                        prediction_content=prediction_content,
                        trace=formatted_trajectory,
                        unimplemented_requirements_to_analyze=unimplemented_context_str
                    )

                    reasons_messages = [{"role": "user", "content": reasons_prompt}]
                    
                    trace_analysis_results = None
                    for attempt in range(max_retries):
                        try:
                            reasons_response = litellm.completion(
                                model="gemini/gemini-2.5-pro",
                                messages=reasons_messages,
                                response_format={"type": "json_schema", "json_schema": {"name": "unimplemented_reasons_trace", "schema": TRACE_BASED_UNIMPLEMENTED_REASONS_JSON_SCHEMA, "strict": True}},
                                temperature=0.2, top_p=1.0, stream=False, n=1, thinkingConfig={"thinkingBudget": -1},
                                api_key=random.choice(GEMINI_API_KEY),
                            )
                            reasons_report_text = reasons_response.choices[0].message.content
                            reason_data = json.loads(reasons_report_text)
                            
                            current_analysis = reason_data.get("unimplemented_requirements_analysis")

                            if current_analysis is not None:
                                analyzed_req_ids = {item['requirement_id'] for item in current_analysis}
                                expected_req_ids = set(unimplemented_reqs)

                                missing_reqs = expected_req_ids - analyzed_req_ids
                                extra_reqs = analyzed_req_ids - expected_req_ids
                                if len(extra_reqs) > 0:
                                    logger.warning(
                                        f"Attempt {attempt + 1}/{max_retries}: Trace analysis mismatch. Missing: {missing_reqs}, Unexpected: {extra_reqs}. Retrying..."
                                    )
                                else:
                                    trace_analysis_results = current_analysis
                                    break
                            else:
                                logger.warning(f"Attempt {attempt + 1}/{max_retries}: Trace analysis result is empty. Retrying...")

                        except Exception as e:
                            logger.warning(
                                f"Attempt {attempt + 1}/{max_retries}: An error occurred during trace-based analysis for unimplemented requirements. Error: {e}. Retrying..."
                            )

                    if trace_analysis_results:
                        final_analysis_report["unimplemented_analysis_by_trace"] = trace_analysis_results
                        logger.info(f"Successfully analyzed trace for all unimplemented requirements for {repo_name}")
                        unimplemented_analysis_done = True
                
                # If all tasks in the loop are done, break
                if general_analysis_done and (unimplemented_analysis_done or not unimplemented_reqs):
                    break

            except Exception as e:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries}: An error occurred during trajectory analysis for {repo_name}. Error: {e}. Retrying..."
                )
        
        # Final check and logging for failures
        if not general_analysis_done:
            logger.error(f"Failed to get a valid general trajectory analysis for {repo_name} after {max_retries} attempts.")
            final_analysis_report["general_analysis"] = None
        
        unimplemented_reqs = evaluation_report.get("unimplemented_requirements", [])
        if unimplemented_reqs and not unimplemented_analysis_done:
            logger.error(f"Failed to get a valid trace-based analysis for unimplemented requirements for {repo_name} after {max_retries} attempts.")
            final_analysis_report["unimplemented_analysis_by_trace"] = []

        return final_analysis_report

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error processing trajectory file for {repo_name}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during trajectory analysis for {repo_name}: {e}")
        
    return None


def evaluate_repo(repo_info: dict, skip_analyze_trajectory: bool = False, prediction_path_dir: str = None):
    """
    Evaluates a repository by calling LLMs for code quality and trajectory analysis.

    :param repo_info: A dictionary containing repository information.
    :param skip_analyze_trajectory: If True, skips the trajectory analysis.
    :return: A dictionary with the evaluation report, or None on failure.
    """
    repo_name = repo_info["repo_name"]
    pred_repo_path = repo_info["repo_path"]
    
    parsed_report = None
    
    # 当我们想要进行轨迹分析时，尝试加载已有的LLM评估结果
    if not skip_analyze_trajectory and prediction_path_dir:
        llm_eval_path = os.path.join(prediction_path_dir, "evaluation_llm.json")
        if os.path.exists(llm_eval_path):
            logger.info(f"找到 {repo_name} 的现有评估文件: {llm_eval_path}，正在加载。")
            try:
                all_results = load_file(llm_eval_path)
                # 从 "details" 列表中查找当前仓库的结果
                for item in all_results.get("details", []):
                    if item.get("repo_name") == repo_name and item.get("result"):
                        parsed_report = item["result"]
                        logger.info(f"成功为 {repo_name} 加载现有评估结果。")
                        break
                if not parsed_report:
                    logger.warning(f"在 {llm_eval_path} 中未找到 {repo_name} 的评估结果。")
            except Exception as e:
                logger.error(f"加载或解析 {llm_eval_path} 时出错: {e}")

    # 如果未能从文件加载报告，则调用LLM进行评估
    if parsed_report is None:
        try:
            reference_content, prediction_content, tests_report = _prepare_evaluation_inputs(repo_info)
        except Exception as e:
            logger.error(f"为 {repo_name} 准备输入时出错: {e}")
            return None

        parsed_report = _get_llm_evaluation(
            pred_repo_path=pred_repo_path,
            repo_name=repo_name,
            project_requirement=repo_info["project_requirement"],
            project_requirement_structured=repo_info["project_requirement_structured"],
            reference_content=reference_content,
            prediction_content=prediction_content,
            tests_report=tests_report,
        )
        
        filtered_test_summary = filter_test_result(repo_info["test_result"])
        parsed_report = {**parsed_report, **filtered_test_summary}

    if parsed_report is None:
        logger.error(f"获取 {repo_name} 的评估报告失败。")
        return None
    
    traj_path = repo_info.get("traj_path")
    if not skip_analyze_trajectory and traj_path:
        # 为轨迹分析准备输入，特别是 prediction_content
        try:
            _, prediction_content, _ = _prepare_evaluation_inputs(repo_info)
        except Exception as e:
            logger.error(f"为 {repo_name} 的轨迹分析准备输入时出错: {e}")
            # 即使准备失败，我们仍然可以返回已有的评估报告
            return parsed_report
            
        trace_analysis_results = _analyze_trajectory(
            traj_path=traj_path,
            repo_name=repo_name,
            project_requirement=repo_info["project_requirement"],
            project_requirement_structured=repo_info["project_requirement_structured"],
            prediction_content=prediction_content,
            evaluation_report=parsed_report,
            unimplemented_analysis_by_code=parsed_report.get("unimplemented_analysis_by_code", [])
        )
        parsed_report["traj_path"] = traj_path
        if trace_analysis_results:
            parsed_report["trace_analysis"] = trace_analysis_results.get("general_analysis")
            unimplemented_analysis = trace_analysis_results.get("unimplemented_analysis_by_trace")
            if unimplemented_analysis:
                parsed_report["unimplemented_analysis_by_trace"] = unimplemented_analysis
    
    return parsed_report


def calculate_and_update_average_results(final_overall, test_type, total_counts, total_coverage_counts, total_coverage_rates, valid_count):
    """Calculates average test results and coverage, then updates the final report dictionary."""
    if valid_count == 0:
        return

    avg_counts = {k: round(v / valid_count, 2) for k, v in total_counts.items()}
    
    avg_coverage_stats = {k: round(v / valid_count, 2) for k, v in total_coverage_counts.items()}

    # Method 1: Existing calculation (rate from totals)
    num_statements = total_coverage_counts.get("num_statements", 0)
    if num_statements > 0:
        avg_coverage_stats["line_coverage_rate"] = round((total_coverage_counts.get("covered_lines", 0) / num_statements) * 100, 2)
    else:
        avg_coverage_stats["line_coverage_rate"] = 0.0

    num_branches = total_coverage_counts.get("num_branches", 0)
    if num_branches > 0:
        avg_coverage_stats["branch_coverage_rate"] = round((total_coverage_counts.get("covered_branches", 0) / num_branches) * 100, 2)
    else:
        avg_coverage_stats["branch_coverage_rate"] = 0.0

    # Method 2: New calculation (average of rates)
    avg_coverage_stats["average_of_line_coverage_rates"] = round(total_coverage_rates.get("line_coverage_rate", 0) / valid_count, 2)
    avg_coverage_stats["average_of_branch_coverage_rates"] = round(total_coverage_rates.get("branch_coverage_rate", 0) / valid_count, 2)

    avg_counts["coverage"] = avg_coverage_stats
    if "average_test_results" not in final_overall:
        final_overall["average_test_results"] = {}
    final_overall["average_test_results"][test_type] = avg_counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run repo evaluation.")
    parser.add_argument(
        "--dataset_file",
        type=str,
        default="../data/python_dataset.json",
        help="Path to dataset json file",
    )
    parser.add_argument(
        "--prediction_path",
        type=str,
        default=None,
        help="Path to prediction json file",
    )
    parser.add_argument(
        "--output_path",
        type=str,
        default=None,
        help="Path to output json file",
    )
    parser.add_argument(
        "--target_repos",
        type=str,
        default=None,
        help="Target repos to evaluate, if is None then evaluate all repos in the prediction file",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of workers for parallel evaluation",
    )
    parser.add_argument(
        "--skip_analyze_trajectory",
        action="store_true",
        help="Skip trajectory analysis.",
    )
    args = parser.parse_args()
    # 读取dataset
    dataset = load_file(args.dataset_file)
    dataset_dict = {item["repo_name"]: item for item in dataset}
    # 读取结果
    predictions = load_file(args.prediction_path)
    test_results = load_file(os.path.join(os.path.dirname(args.prediction_path), "evaluation_test.json"))
    test_results = {item["repo_name"]: item for item in test_results["details"]}

    report_list = []
    # 过滤需要评估的项目
    items_to_eval = predictions
    if args.target_repos is not None:
        items_to_eval = [
            item for item in predictions if item["repo_name"] in args.target_repos
        ]
    
    prediction_path_dir = os.path.dirname(args.prediction_path)
    for item in items_to_eval:
        assert os.path.exists(item["repo_source_path"]), f"Repo source path {item['repo_source_path']} does not exist"
        repo_path = os.path.join(os.path.dirname(args.prediction_path), item["repo_name"], item["repo_name"])
        if os.path.exists(repo_path):
            shutil.rmtree(repo_path)
        shutil.copytree(item["repo_source_path"], repo_path)
        patch_path = os.path.join(os.path.dirname(args.prediction_path), item["repo_name"], f"{item['repo_name']}.patch")
        patch_idx = max([int(k) for k in item["model_patch"].keys()])
        patch = item["model_patch"][str(patch_idx)]
        save_file(patch_path, patch)
        success = apply_patch(Path(patch_path), Path(repo_path))
        if not success:
            logger.error(f"Failed to apply patch {patch_path} to {repo_path}")
            continue
        
        item["repo_path"] = repo_path
        item["traj_path"] = os.path.join(os.path.dirname(args.prediction_path), f"../runs/{item['repo_name']}/{item['repo_name']}.traj")
        assert os.path.exists(item["traj_path"]), f"Trajectory file {item['traj_path']} does not exist"
        item["test_result"] = test_results[item["repo_name"]]
        
        project_requirement_path = os.path.join(os.path.dirname(args.prediction_path), f"../repos/_problem_statement/{item['repo_name']}.md")
        project_requirement = load_file(project_requirement_path)
        item["project_requirement"] = project_requirement
        item["project_requirement_structured"] = dataset_dict[item["repo_name"]]["structured_requirements"]

    if args.workers > 1:
        # 并行评估
        logger.info(
            f"Evaluating {len(items_to_eval)} repos with {args.workers} workers"
        )
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=args.workers
        ) as executor:
            future_to_item = {
                executor.submit(evaluate_repo, item, args.skip_analyze_trajectory, prediction_path_dir): item for item in items_to_eval
            }
            # 使用 tqdm 包装 as_completed 来显示进度条
            for future in tqdm(
                concurrent.futures.as_completed(future_to_item),
                total=len(items_to_eval),
                desc="Evaluating Repos",
            ):
                item = future_to_item[future]
                try:
                    result = future.result()
                except Exception as e:
                    # 确保错误信息也被记录到文件中
                    logger.exception(
                        f"Error evaluating {item['repo_name']}"
                    )  # 使用 logger.exception 记录完整堆栈跟踪
                    item["result"] = None
                    report_list.append(item)
                else:
                    item["result"] = result
                    report_list.append(item)
    else:
        # 单线程评估
        logger.info(f"Evaluating {len(items_to_eval)} repos with single thread")
        for item in tqdm(items_to_eval, desc="Evaluating Repos"):
            try:
                result = evaluate_repo(item, args.skip_analyze_trajectory, prediction_path_dir)
                item["result"] = result
                report_list.append(item)
            except Exception as e:
                logger.exception(f"Error evaluating {item['repo_name']}")
                item["result"] = None
                report_list.append(item)

    details = report_list
    final_overall = {}

    total_repos = len(details)
    if total_repos > 0:
        # LLM metrics
        total_completeness = 0
        total_executability = 0
        total_consistency = 0
        valid_reports = 0

        # Failure analysis stats
        failure_stats = {}
        valid_trace_analysis = 0

        # Test metrics
        test_types = ["ori_tests", "new_tests", "all_tests", "reference_test"]
        count_keys = ["success_count", "failed_count", "error_count", "skipped_count", "unknown_count", "total_count"]
        coverage_keys = ["covered_lines", "num_statements", "num_branches", "covered_branches"]
        coverage_rate_keys = ["line_coverage_rate", "branch_coverage_rate"]
        
        total_tests = {t: {k: 0 for k in count_keys} for t in test_types}
        total_tests_coverage = {t: {k: 0 for k in coverage_keys} for t in test_types}
        total_tests_coverage_rates = {t: {k: 0 for k in coverage_rate_keys} for t in test_types}
        valid_tests = {t: 0 for t in test_types}

        for item in details:
            if item.get("result") is None:
                continue
            tests_data = item["result"]
            metrics = tests_data.get("metrics")
            if metrics:
                valid_reports += 1
                total_completeness += metrics.get("completeness", {}).get("score", 0)
                total_executability += metrics.get("executability", {}).get("score", 0)
                total_consistency += metrics.get("consistency", {}).get("score", 0)

            for test_type in test_types:
                test_data = tests_data.get(test_type)
                if test_data:
                    valid_tests[test_type] += 1
                    for k in count_keys:
                        total_tests[test_type][k] += test_data.get(k, 0)
                    if "coverage" in test_data and test_data["coverage"]:
                        for k in coverage_keys:
                            total_tests_coverage[test_type][k] += test_data["coverage"].get(k, 0)
                        for k in coverage_rate_keys:
                            total_tests_coverage_rates[test_type][k] += test_data["coverage"].get(k, 0)
            
            trace_analysis_data = tests_data.get("trace_analysis")
            if trace_analysis_data:
                valid_trace_analysis += 1
                for type_id, detail in trace_analysis_data.get("failure_types", {}).items():
                    if type_id not in failure_stats:
                        failure_stats[type_id] = {"count": 0, "repos": []}
                    if detail.get("has_appeared") == "yes":
                        failure_stats[type_id]["count"] += 1
                        failure_stats[type_id]["repos"].append(item["repo_name"])

            unimplemented_by_trace = tests_data.get("unimplemented_analysis_by_trace")
            if unimplemented_by_trace:
                for analysis in unimplemented_by_trace:
                    req = analysis.get("requirement")
                    if req:
                        if "unimplemented_analysis_summary_by_trace" not in final_overall:
                            final_overall["unimplemented_analysis_summary_by_trace"] = {}
                        if req not in final_overall["unimplemented_analysis_summary_by_trace"]:
                            final_overall["unimplemented_analysis_summary_by_trace"][req] = []
                        final_overall["unimplemented_analysis_summary_by_trace"][req].append({
                            "repo_name": item["repo_name"],
                            "analysis": analysis.get("trace_evidence_and_analysis"),
                            "failure_classification": analysis.get("failure_classification")
                        })

        # Calculate averages for LLM scores
        if valid_reports > 0:
            avg_completeness = total_completeness / valid_reports
            avg_executability = total_executability / valid_reports
            avg_consistency = total_consistency / valid_reports
            overall_avg = (avg_completeness + avg_executability + avg_consistency) / 3

            final_overall = {
                "total_evaluated": total_repos,
                "valid_reports": valid_reports,
                "average_scores": {
                    "completeness": round(avg_completeness, 2),
                    "executability": round(avg_executability, 2),
                    "consistency": round(avg_consistency, 2),
                },
                "overall_average_score": round(overall_avg, 2),
                "average_test_results": {}
            }

        if valid_trace_analysis > 0:
            final_overall["failure_analysis_summary"] = {
                "total_analyzed": valid_trace_analysis,
                "failure_counts": failure_stats,
                "failure_rates": {k: round(v["count"] / valid_trace_analysis, 2) for k, v in failure_stats.items()}
            }

        # Calculate averages for all test types
        for test_type in test_types:
            calculate_and_update_average_results(
                final_overall,
                test_type,
                total_tests[test_type],
                total_tests_coverage[test_type],
                total_tests_coverage_rates[test_type],
                valid_tests[test_type]
            )

    report = {
        "overall": final_overall,
        "details": details,
    }
    logger.info(
        f"Evaluation Report: \n{json.dumps(report['overall'], ensure_ascii=False, indent=4)}"
    )
    # 保存评估结果
    if args.output_path is None:
        if not args.skip_analyze_trajectory:
            args.output_path = os.path.join(os.path.dirname(args.prediction_path), "evaluation_llm_with_trace.json")
        else:
            args.output_path = os.path.join(os.path.dirname(args.prediction_path), "evaluation_llm.json")
    with open(args.output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=4)
