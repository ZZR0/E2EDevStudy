# 大模型api的包装函数
# 用于调用大模型api，返回结果

import time
import openai

from loguru import logger
from utils.config import BASE_URL, API_KEY
from utils.utils import get_json_schema, parse_structured_output


class LLM:
    _instance = None
    _total_token_usage = 0
    _prompt_token_usage = 0
    _completion_token_usage = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def total_tokens(self) -> int:
        return self.__class__._total_token_usage

    @property
    def prompt_tokens(self) -> int:
        return self.__class__._prompt_token_usage

    @property
    def completion_tokens(self) -> int:
        return self.__class__._completion_token_usage

    @classmethod
    def call_llm(
        cls,
        model_name: str,
        messages: list,
        max_retries: int = 3,
        base_delay: int = 2,
    ):
        """
        Call the LLM API to generate text based on the given prompts.

        Args:
            model_name (str): The name of the model to use.
            system_prompt (str): The system prompt to provide to the model.
            user_prompts (list): A list of user prompts to provide to the model.
            max_retries (int): The maximum number of retries in case of failure.
            base_delay (int): The base delay between retries.

        Returns:
            str: The generated text.
        """
        # 检查messages所有内容的总长度
        total_length = sum(len(message["content"]) for message in messages)
        logger.info(f"Calling llm, total message length: {total_length}")
        if total_length > 500000:
            logger.warning("Total message length exceeds 500000")
            # 输出消息每个部分的长度
            for message in messages:
                logger.warning(f"Message length: {len(message['content'])}")

        client = openai.OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
        )
        for attempt in range(max_retries):
            try:
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                )
                answer = completion.choices[0].message.content
                token_usage = completion.usage.total_tokens
                logger.info(f"Token usage: {token_usage}")
                LLM._total_token_usage += token_usage
                LLM._prompt_token_usage += completion.usage.prompt_tokens
                LLM._completion_token_usage += completion.usage.completion_tokens
                return answer
            except Exception as e:
                logger.error(e)
                logger.warning(f"Failed to generate text: {e}, retrying {attempt + 1} ...")
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    time.sleep(delay)

        logger.error("Failed to generate text")
        return None

    @classmethod
    def call_llm_with_structured_output(
        cls,
        model_name: str,
        messages: list,
        structured_output_class,
        temperature: float = 0.0,
        max_retries: int = 3,
        base_delay: int = 2,
    ):
        """
        Call the LLM API to generate text based on the given prompts and return structured output.

        Args:
            model_name (str): The name of the model to use.
            system_prompt (str): The system prompt to provide to the model.
            user_prompts (list): A list of user prompts to provide to the model.
            structured_output_class (class): The class to use for parsing the structured output.
            max_retries (int): The maximum number of retries in case of failure.
            base_delay (int): The base delay between retries.

        Returns:
            object: The structured output.
        """
        # 检查messages所有内容的总长度
        total_length = sum(len(message["content"]) for message in messages)
        logger.info(f"Calling llm, total message length: {total_length}")
        if total_length > 700000:
            logger.warning("Total message length exceeds 700000")

        client = openai.OpenAI(
            base_url=BASE_URL,
            api_key=API_KEY,
        )
        # import pdb; pdb.set_trace()
        for attempt in range(max_retries):
            try:
                response_format = get_json_schema(structured_output_class)
                
                completion = client.chat.completions.create(                
                    model=model_name,                
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format            
                )
                output = parse_structured_output(structured_output_class, completion.choices[0].message.content)
                
                # completion = client.beta.chat.completions.parse(
                #     model=model_name,
                #     messages=messages,
                #     response_format=structured_output_class,
                # )
                # output = completion.choices[0].message.parsed
                
                token_usage = completion.usage.total_tokens
                logger.info(f"Token usage: {token_usage}")
                LLM._total_token_usage += token_usage
                LLM._prompt_token_usage += completion.usage.prompt_tokens
                LLM._completion_token_usage += completion.usage.completion_tokens
                return output
            except Exception as e:
                logger.error(e)
                logger.warning(f"Failed to generate text: {e}, retrying {attempt + 1} ...")
                if "sensitive_words_detected" in str(e):
                    logger.error("Sensitive words detected, skipping...")
                    return structured_output_class()
                if "exceeds the maximum number of tokens allowed" in str(e):
                    logger.error("Exceeds the maximum number of tokens allowed, skipping...")
                    return structured_output_class()
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    time.sleep(delay)

        logger.error("Failed to generate text")
        return None
