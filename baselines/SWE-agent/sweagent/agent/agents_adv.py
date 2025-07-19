from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from typing_extensions import Self

from sweagent import __version__, get_agent_commit_hash, get_rex_commit_hash, get_rex_version
from sweagent.agent.agents import (
    AbstractAgent,
    DefaultAgent,
    DefaultAgentConfig,
    DevTestAgentConfig,
    DesignDevTestAgentConfig,
)
from sweagent.agent.hooks.abstract import AbstractAgentHook, CombinedAgentHook
from sweagent.agent.models import InstanceStats, get_model
from sweagent.agent.problem_statement import ProblemStatement, ProblemStatementConfig
from sweagent.environment.swe_env import SWEEnv
from sweagent.tools.tools import ToolHandler
from sweagent.types import AgentInfo, AgentRunResult, StepOutput, Trajectory
from sweagent.utils.log import get_logger

class AdvDefaultAgent(DefaultAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def attempt_autosubmission_after_error(self, step: StepOutput) -> StepOutput:
        """
        For most exceptions, we attempt to still extract the patch and submit that.
        This version first finds the step with the maximum number of passed tests,
        resets to that state, and then attempts to submit.
        """
        self.logger.warning("Attempting autosubmission after error")

        # Find the step with the maximum number of passed tests and reset to it.
        best_step_for_reset = 0
        max_passed = -1
        for i, traj_step in enumerate(self.trajectory):
            state = traj_step.get("state", {})
            if "pytest_output" in state and state["pytest_output"]:
                try:
                    # The pytest_output is a string which is a JSON representation of test results
                    pytest_results = json.loads(state["pytest_output"])
                    if isinstance(pytest_results, str):
                        # It might be double-encoded
                        pytest_results = json.loads(pytest_results)

                    passed_count = pytest_results.get("summary", {}).get("passed", -1)

                    if passed_count >= max_passed:
                        max_passed = passed_count
                        # reset_to_step is 1-indexed, trajectory is 0-indexed
                        best_step_for_reset = i + 1
                except (json.JSONDecodeError, TypeError) as e:
                    self.logger.warning(f"Could not parse pytest_output for step {i + 1}: {e}")
                    continue

        if best_step_for_reset > 0:
            self.logger.info(
                f"Found best step {best_step_for_reset} with {max_passed} passed tests. "
                "Resetting agent to that state before submission."
            )
            try:
                self.reset_to_step(best_step_for_reset)
            except Exception as e:
                self.logger.error(
                    f"Failed to reset to step {best_step_for_reset}, will try to submit from current state. Error: {e}",
                    exc_info=True,
                )

        # Call the original submission logic after attempting to reset.
        return super().attempt_autosubmission_after_error(step)

    def reset_to_step(self, step: int) -> None:
        """
        Resets the agent and environment to the state *after* a specific step has been executed.

        This will modify the agent's `history` and `trajectory` to match the state
        after the given step was executed. The environment will also be reverted
        to the corresponding code state by applying the diff from that step.

        Args:
            step (int): The step number (1-indexed) to reset to. Step 0 means resetting
                        to the initial state before any steps have been run.
                        After reset, the agent will be ready to execute step `step + 1`.
        """
        self.logger.info(f"Attempting to reset agent and environment to after step {step}")

        # The valid range for `step` is from 0 (before step 1) up to the number of steps completed.
        if not (0 <= step <= len(self._trajectory)):
            msg = f"Invalid step number {step}. Must be between 0 and {len(self._trajectory)}"
            self.logger.error(msg)
            raise ValueError(msg)

        # 1. Reset environment to the state after the target step
        self.logger.info(f"Resetting environment to state after step {step}")
        assert self._env is not None
        if step == 0:
            # If resetting to after step 0, we want a clean environment (state before step 1).
            self._env.reset()
        else:
            # For subsequent steps, restore from the state captured after the target step.
            # Trajectory is 0-indexed, state after step `k` is at index `k-1`.
            state_to_restore = self._trajectory[step - 1]["state"]
            self._env.reset_to_state(state_to_restore)

        # 2. Reset agent's trajectory to contain all steps up to and including the target step
        self.logger.info(f"Resetting agent trajectory to after step {step}")
        self._trajectory = self._trajectory[:step]

        # 3. Reset agent's history by rebuilding it from the truncated trajectory
        self.logger.info(f"Rebuilding agent history up to step {step}")
        # Start with a clean history and re-run the setup steps that populate it.
        # This is more robust than trying to slice the old history list.
        self.history = []
        self.add_system_message_to_history()
        self.add_demonstrations_to_history()
        assert self._env is not None
        self.add_instance_template_to_history(state=self.tools.get_state(self._env))
        for trajectory_step in self._trajectory:
            # Recreate a StepOutput object to pass to add_step_to_history
            step_output = StepOutput(
                action=trajectory_step["action"],
                observation=trajectory_step["observation"],
                output=trajectory_step["response"],
                thought=trajectory_step["thought"],
                state=trajectory_step["state"],
                tool_calls=trajectory_step.get("tool_calls"),
                tool_call_ids=[call["id"] for call in trajectory_step.get("tool_calls", [])]
            )
            self.add_step_to_history(step_output)

        # 4. Reset info object
        self.logger.info("Resetting agent info object")
        self.info = AgentInfo()
        self.info["swe_agent_hash"] = get_agent_commit_hash()
        self.info["swe_agent_version"] = __version__
        self.info["swe_rex_version"] = get_rex_version()
        self.info["swe_rex_hash"] = get_rex_commit_hash()

        self.logger.info(f"Successfully reset agent to step {step}")
        
        
class DevTestAgent(AbstractAgent):
    def __init__(self, config: DevTestAgentConfig):
        # Always copy config to avoid shared state between different instances
        self.config = config.model_copy(deep=True)
        self._hooks = []
        self.logger = get_logger("swea-agent", emoji="🤠")
        self._agent_dev: DefaultAgent | None = None
        self._agent_test: DefaultAgent | None = None
        self._current_agent: DefaultAgent | None = None
        self._dev_trajectory = []
        self._dev_info = {}

        self._chook = CombinedAgentHook()
        self._traj_path: Path | None = None
        self._problem_statement: ProblemStatement | None = None
        self._env: SWEEnv | None = None
        self._output_dir: Path | None = None

    @classmethod
    def from_config(cls, config: DevTestAgentConfig) -> Self:
        return cls(config)

    def add_hook(self, hook: AbstractAgentHook) -> None:
        self._chook.add_hook(hook)
        self._hooks.append(hook)

    def setup(
        self, env: SWEEnv, problem_statement: ProblemStatement | ProblemStatementConfig, output_dir: Path = Path(".")
    ) -> None:
        """Setup the agent for a new problem instance.
        This is mostly a bookkeeping step.
        """
        self._problem_statement = problem_statement
        self._traj_path = output_dir / (self._problem_statement.id + ".traj")
        self._env = env
        self._output_dir = output_dir

    def _setup_dev_agent(self) -> None:
        self.logger.info("Setting up dev agent")
        assert self._env is not None
        assert self._problem_statement is not None
        assert self._output_dir is not None

        dev_config = self.config.dev.model_copy(deep=True)
        self._agent_dev = AdvDefaultAgent.from_config(dev_config)
        for hook in self._hooks:
            self._agent_dev.add_hook(hook)

        dev_output_dir = self._output_dir / "dev_agent"
        dev_output_dir.mkdir(parents=True, exist_ok=True)
        self._agent_dev.setup(env=self._env, problem_statement=self._problem_statement, output_dir=dev_output_dir)
        self._current_agent = self._agent_dev

    def _setup_test_agent(self) -> None:
        self.logger.info("Setting up test agent")
        assert self._env is not None
        assert self._problem_statement is not None
        assert self._output_dir is not None

        test_config = self.config.test.model_copy(deep=True)
        self._agent_test = AdvDefaultAgent.from_config(test_config)
        for hook in self._hooks:
            self._agent_test.add_hook(hook)

        test_output_dir = self._output_dir / "test_agent"
        test_output_dir.mkdir(parents=True, exist_ok=True)
        self._agent_test.setup(env=self._env, problem_statement=self._problem_statement, output_dir=test_output_dir)
        self._current_agent = self._agent_test

    def step(self) -> StepOutput:
        assert self._current_agent is not None
        step_output = self._current_agent.step()
        self._current_agent.save_trajectory()
        return step_output

    def get_trajectory_data(self) -> dict[str, Any]:
        assert self._agent_dev is not None
        assert self._agent_test is not None

        dev_data = self._agent_dev.get_trajectory_data()
        test_data = self._agent_test.get_trajectory_data()
        
        dev_data["trajectory"] = [{"agent": self._agent_dev.name, **item} for item in dev_data["trajectory"]]
        test_data["trajectory"] = [{"agent": self._agent_test.name, **item} for item in test_data["trajectory"]]
        
        dev_data["history"] = [{"agent": self._agent_dev.name, **item} for item in dev_data["history"]]
        test_data["history"] = [{"agent": self._agent_test.name, **item} for item in test_data["history"]]
        
        combined_trajectory = dev_data["trajectory"] + test_data["trajectory"]
        combined_history = dev_data["history"] + test_data["history"]

        info = test_data["info"]
        info["dev_model_stats"] = dev_data["info"]["model_stats"]
        info["test_model_stats"] = test_data["info"]["model_stats"]

        total_stats = InstanceStats.model_validate(dev_data["info"]["model_stats"]) + InstanceStats.model_validate(
            test_data["info"]["model_stats"]
        )
        info["model_stats"] = total_stats.model_dump()

        data = {
            "trajectory": combined_trajectory,
            "history": combined_history,
            "info": info,
            "dev_trajectory": dev_data["trajectory"],
            "test_trajectory": test_data["trajectory"],
        }
        return data

    def save_trajectory(self) -> None:
        data = self.get_trajectory_data()
        assert self._traj_path is not None
        self._traj_path.write_text(json.dumps(data, indent=2))

    def run(
        self,
        env: SWEEnv,
        problem_statement: ProblemStatement | ProblemStatementConfig,
        output_dir: Path = Path("."),
    ) -> AgentRunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.setup(env=env, problem_statement=problem_statement, output_dir=output_dir)

        self._chook.on_run_start()

        # Dev agent phase
        self._setup_dev_agent()
        step_output = StepOutput()
        self.logger.info("Running Dev Agent...")
        while not step_output.done:
            step_output = self.step()

        self.logger.info("Dev Agent finished.")
        used_calls_count = self._agent_dev.model.stats.api_calls
        # Test agent phase
        self._setup_test_agent()
        
        self._current_agent.model.config.per_instance_call_limit -= used_calls_count
        step_output = StepOutput()
        self.logger.info("Running Test Agent...")
        while not step_output.done:
            step_output = self.step()

        self.logger.info("Test Agent finished.")

        self.save_trajectory()
        self._chook.on_run_done(
            trajectory=self.get_trajectory_data()["trajectory"], info=self.get_trajectory_data()["info"]
        )

        self.logger.info("Trajectory saved to %s", self._traj_path)

        data = self.get_trajectory_data()
        return AgentRunResult(info=data["info"], trajectory=data["trajectory"])


class DesignDevTestAgent(DevTestAgent):
    def __init__(self, config: DesignDevTestAgentConfig):
        super().__init__(config)
        self._agent_design: DefaultAgent | None = None

    def _setup_design_agent(self) -> None:
        self.logger.info("Setting up design agent")
        assert self._env is not None
        assert self._problem_statement is not None
        assert self._output_dir is not None

        design_config = self.config.design.model_copy(deep=True)
        self._agent_design = AdvDefaultAgent.from_config(design_config)
        for hook in self._hooks:
            self._agent_design.add_hook(hook)

        design_output_dir = self._output_dir / "design_agent"
        design_output_dir.mkdir(parents=True, exist_ok=True)
        self._agent_design.setup(env=self._env, problem_statement=self._problem_statement, output_dir=design_output_dir)
        self._current_agent = self._agent_design

    def get_trajectory_data(self) -> dict[str, Any]:
        assert self._agent_design is not None
        assert self._agent_dev is not None
        assert self._agent_test is not None

        design_data = self._agent_design.get_trajectory_data()
        dev_data = self._agent_dev.get_trajectory_data()
        test_data = self._agent_test.get_trajectory_data()

        design_data["trajectory"] = [{"agent": self._agent_design.name, **item} for item in design_data["trajectory"]]
        dev_data["trajectory"] = [{"agent": self._agent_dev.name, **item} for item in dev_data["trajectory"]]
        test_data["trajectory"] = [{"agent": self._agent_test.name, **item} for item in test_data["trajectory"]]

        design_data["history"] = [{"agent": self._agent_design.name, **item} for item in design_data["history"]]
        dev_data["history"] = [{"agent": self._agent_dev.name, **item} for item in dev_data["history"]]
        test_data["history"] = [{"agent": self._agent_test.name, **item} for item in test_data["history"]]

        combined_trajectory = design_data["trajectory"] + dev_data["trajectory"] + test_data["trajectory"]
        combined_history = design_data["history"] + dev_data["history"] + test_data["history"]

        info = test_data["info"]
        info["design_model_stats"] = design_data["info"]["model_stats"]
        info["dev_model_stats"] = dev_data["info"]["model_stats"]
        info["test_model_stats"] = test_data["info"]["model_stats"]

        total_stats = (
            InstanceStats.model_validate(design_data["info"]["model_stats"])
            + InstanceStats.model_validate(dev_data["info"]["model_stats"])
            + InstanceStats.model_validate(test_data["info"]["model_stats"])
        )
        info["model_stats"] = total_stats.model_dump()

        data = {
            "trajectory": combined_trajectory,
            "history": combined_history,
            "info": info,
            "design_trajectory": design_data["trajectory"],
            "dev_trajectory": dev_data["trajectory"],
            "test_trajectory": test_data["trajectory"],
        }
        return data

    def run(
        self,
        env: SWEEnv,
        problem_statement: ProblemStatement | ProblemStatementConfig,
        output_dir: Path = Path("."),
    ) -> AgentRunResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.setup(env=env, problem_statement=problem_statement, output_dir=output_dir)

        self._chook.on_run_start()

        total_used_calls = 0

        # Design agent phase
        self._setup_design_agent()
        step_output = StepOutput()
        self.logger.info("Running Design Agent...")
        while not step_output.done:
            step_output = self.step()
        self.logger.info("Design Agent finished.")
        total_used_calls += self._agent_design.model.stats.api_calls

        # Dev agent phase
        self._setup_dev_agent()
        self._current_agent.model.config.per_instance_call_limit -= total_used_calls
        step_output = StepOutput()
        self.logger.info("Running Dev Agent...")
        while not step_output.done:
            step_output = self.step()

        self.logger.info("Dev Agent finished.")
        total_used_calls += self._agent_dev.model.stats.api_calls

        # Test agent phase
        self._setup_test_agent()
        self._current_agent.model.config.per_instance_call_limit -= total_used_calls
        step_output = StepOutput()
        self.logger.info("Running Test Agent...")
        while not step_output.done:
            step_output = self.step()

        self.logger.info("Test Agent finished.")

        self.save_trajectory()
        self._chook.on_run_done(
            trajectory=self.get_trajectory_data()["trajectory"], info=self.get_trajectory_data()["info"]
        )

        self.logger.info("Trajectory saved to %s", self._traj_path)

        data = self.get_trajectory_data()
        return AgentRunResult(info=data["info"], trajectory=data["trajectory"])


class Branch(BaseModel):
    id: str
    parent_id: str | None = None
    fork_step: int | None = None
    trajectory: Trajectory = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)
    info: AgentInfo = Field(default_factory=AgentInfo)


class TreeDefaultAgent(AdvDefaultAgent):
    def __init__(
        self,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.branches: dict[str, Branch] = {}
        self.next_branch_id_int = 0
        self.current_branch_id: str | None = None

    @classmethod
    def from_config(cls, config: DefaultAgentConfig) -> Self:
        config = config.model_copy(deep=True)
        model = get_model(config.model, config.tools)
        return cls(
            templates=config.templates,
            tools=ToolHandler(config.tools),
            history_processors=config.history_processors,
            model=model,
            max_requeries=config.max_requeries,
            action_sampler_config=config.action_sampler,
        )

    # State properties now point to the current branch
    @property
    def history(self) -> list[dict[str, Any]]:
        if self.current_branch_id is None:
            return []
        return self.branches[self.current_branch_id].history

    @history.setter
    def history(self, value: list[dict[str, Any]]):
        if self.current_branch_id is None:
            raise RuntimeError("No current branch selected to set history")
        self.branches[self.current_branch_id].history = value

    @property
    def trajectory(self) -> Trajectory:
        if self.current_branch_id is None:
            return []
        return self.branches[self.current_branch_id].trajectory

    @trajectory.setter
    def trajectory(self, value: Trajectory):
        if self.current_branch_id is None:
            raise RuntimeError("No current branch selected to set trajectory")
        self.branches[self.current_branch_id].trajectory = value

    @property
    def info(self) -> AgentInfo:
        if self.current_branch_id is None:
            return AgentInfo()
        return self.branches[self.current_branch_id].info

    @info.setter
    def info(self, value: AgentInfo):
        if self.current_branch_id is None:
            raise RuntimeError("No current branch selected to set info")
        self.branches[self.current_branch_id].info = value

    def _rebuild_history_from_trajectory(self, trajectory: Trajectory) -> list[dict]:
        """Helper to reconstruct history from a trajectory"""
        # Create a temporary 'dummy' agent to rebuild history, to not mess with self state
        # This is a bit of a hack, but it's the most reliable way to reconstruct history
        temp_agent = DefaultAgent(
            templates=self.templates,
            tools=self.tools,
            history_processors=self.history_processors,
            model=self.model,
        )
        temp_agent._env = self._env
        temp_agent._problem_statement = self._problem_statement

        temp_agent.history = []
        temp_agent.add_system_message_to_history()
        temp_agent.add_demonstrations_to_history()
        assert self._env is not None
        temp_agent.add_instance_template_to_history(state=self.tools.get_state(self._env))
        for trajectory_step in trajectory:
            step_output = StepOutput(
                action=trajectory_step["action"],
                observation=trajectory_step["observation"],
                output=trajectory_step["response"],
                thought=trajectory_step["thought"],
                state=trajectory_step["state"],
                tool_calls=trajectory_step.get("tool_calls"),
                tool_call_ids=[call["id"] for call in trajectory_step.get("tool_calls", [])],
            )
            temp_agent.add_step_to_history(step_output)
        return temp_agent.history

    def _create_new_branch(
        self, parent_id: str | None, fork_step: int | None, trajectory_prefix: Trajectory | None = None
    ) -> str:
        new_id = str(self.next_branch_id_int)
        self.next_branch_id_int += 1

        if parent_id is None:
            # Root branch
            new_branch = Branch(id=new_id)
        else:
            if trajectory_prefix is None:
                parent_branch = self.branches[parent_id]
                trajectory_prefix = parent_branch.trajectory[:fork_step]
            # Rebuild history from this prefix
            history_prefix = self._rebuild_history_from_trajectory(trajectory_prefix)
            new_branch = Branch(
                id=new_id,
                parent_id=parent_id,
                fork_step=fork_step,
                trajectory=trajectory_prefix,
                history=history_prefix,
            )

        self.branches[new_id] = new_branch
        return new_id

    def setup(
        self,
        env: SWEEnv,
        problem_statement: ProblemStatement | ProblemStatementConfig,
        output_dir: Path = Path("."),
    ) -> None:
        """Setup the agent for a new instance, creating the root branch."""
        # Most of setup is the same as DefaultAgent, but we need to initialize the tree
        output_dir.mkdir(parents=True, exist_ok=True)
        self._problem_statement = problem_statement
        self._env = env
        iid = self._problem_statement.id
        self.logger.info("Setting up tree agent for instance %s", iid)
        self.traj_path = output_dir / (self._problem_statement.id + ".traj")
        self.logger.info("Trajectory will be saved to %s", self.traj_path)

        self._chook.on_tools_installation_started()
        self.tools.install(self._env)
        self._chook.on_setup_attempt()

        # Initialize the tree structure
        self.branches = {}
        self.next_branch_id_int = 0
        self.current_branch_id = self._create_new_branch(parent_id=None, fork_step=None)

        # Now, populate the history for the root branch using existing methods
        # The properties will ensure this applies to the current (root) branch
        self.info = AgentInfo()
        self.info["swe_agent_hash"] = "DUMMY_HASH"  # get_agent_commit_hash()
        self.info["swe_agent_version"] = "DUMMY_VERSION"  # __version__
        self.info["swe_rex_version"] = "DUMMY_REX_VERSION"  # get_rex_version()
        self.info["swe_rex_hash"] = "DUMMY_REX_HASH"  # get_rex_commit_hash()

        assert self._env is not None
        assert self._problem_statement is not None
        self._env.set_env_variables({"PROBLEM_STATEMENT": self._problem_statement.get_problem_statement()})
        self.add_system_message_to_history()
        self.add_demonstrations_to_history()
        self.add_instance_template_to_history(state=self.tools.get_state(self._env))
        self._chook.on_setup_done()

    def reset_to_step(self, branch_id: str, step: int):
        """Creates a new branch from a specified point and switches to it."""
        self.logger.info(f"Forking a new branch from branch '{branch_id}' after step {step}")

        if branch_id not in self.branches:
            msg = f"Branch '{branch_id}' not found."
            self.logger.error(msg)
            raise ValueError(msg)

        parent_branch = self.branches[branch_id]
        if not (0 <= step <= len(parent_branch.trajectory)):
            msg = f"Invalid step number {step}. Must be between 0 and {len(parent_branch.trajectory)}"
            self.logger.error(msg)
            raise ValueError(msg)

        # Create the new branch
        new_branch_id = self._create_new_branch(parent_id=branch_id, fork_step=step)

        # Switch to the new branch
        self.current_branch_id = new_branch_id
        self.logger.info(f"Switched to new branch '{new_branch_id}'")

        # Reset the environment to the state at the fork point
        self.logger.info(f"Resetting environment to state after step {step} from branch '{branch_id}'")
        assert self._env is not None
        if step == 0:
            self._env.reset()
        else:
            state_to_restore = parent_branch.trajectory[step - 1]["state"]
            self._env.reset_to_state(state_to_restore)
        self.logger.info("Environment reset complete.")

    def get_trajectory_data(self) -> dict[str, Any]:
        """Get all data that we save in .traj files, including all branches."""
        if self.current_branch_id is None:
            return {}

        branches_data = {}
        for branch_id, branch in self.branches.items():
            branches_data[branch_id] = branch.model_dump(exclude={"history"})

        # Get data from the current branch to fill top-level fields for compatibility
        current_branch_data = super().get_trajectory_data()
        current_branch_data["branches"] = branches_data
        current_branch_data["current_branch_id"] = self.current_branch_id

        return current_branch_data

    # run() method from DefaultAgent is compatible and can be inherited
    # step() method from DefaultAgent is compatible and can be inherited
    # forward_with_handling() and other core logic are compatible due to property overrides