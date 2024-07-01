import json
import random
from itertools import permutations

from datasets import Dataset


class Prompt:
    def __init__(self, question, k, options=None, context=None, chat_format=None):
        self.question = question
        self.options = options
        self.context = context
        self.k = k
        self.chat_format = chat_format

    def __str__(self):
        if self.chat_format == "llama_chat_simple":
            return self.llama_chat_format()
        elif self.chat_format == "llama_chat_v2":
            return self.llama_chat_formatv2()
        elif self.chat_format == "llama_cot_chat":
            return self.llama_cot_chat_format()
        return self.base_format()

    def base_format(self):
        prompt = ""
        if self.question:
            prompt += f"[Question] {self.question}\n"
        if self.context:
            prompt += f"[Context] {self.context}\n"
        if self.options:
            prompt += f"[Options] {self.options}\n"
        if self.k:
            prompt += f"[Number of answers] {self.k}\n"
        prompt += "[Answer 1] "
        return prompt

    def llama_chat_format(self):
        template = (
            "<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{user_message} [/INST]"
        )
        sys_prompt = (
            f"Generate {self.k} different reasoning chains that answer the question."
        )
        user_message = ""
        if self.question:
            user_message += f"[Question] {self.question}\n"
        if self.context:
            user_message += f"[Context] {self.context}\n"
        if self.options:
            user_message += f"[Options] {self.options}\n"
        user_message += "[Answer 1]"
        return template.format(system_prompt=sys_prompt, user_message=user_message)

    def llama_cot_chat_format(self):
        template = (
            "<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{user_message} [/INST]"
        )
        sys_prompt = f"Generate a reasoning chain that answer the question."
        user_message = ""
        if self.question:
            user_message += f"[Question] {self.question}\n"
        if self.context:
            user_message += f"[Context] {self.context}\n"
        if self.options:
            user_message += f"[Options] {self.options}\n"
        user_message += "[Answer 1]"
        return template.format(system_prompt=sys_prompt, user_message=user_message)

    def llama_chat_formatv2(self):
        template = (
            "<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n\n{user_message} [/INST]"
        )
        sys_prompt = f"Generate {self.k} different reasoning chains that answer the question. Make sure that none of the reasoning chains are repeated. Generate each reasoning chain independently, and not based on previous reasoning chains. This means that each reasoning chain must be as different from the others as possible. When generating the different reasoning chains, do so without knowledge of the answer. Each step in each of the reasoning chains must build on the previous steps in that reasoning chain. Once the required number of reasoning chains are generated, generate an answer based on the all the answers generated by all the reasoning chains."
        user_message = ""
        if self.question:
            user_message += f"[Question] {self.question}\n"
        if self.context:
            user_message += f"[Context] {self.context}\n"
        if self.options:
            user_message += f"[Options] {self.options}\n"
        user_message += "[Answer 1]"
        return template.format(system_prompt=sys_prompt, user_message=user_message)


class DataProcessorMode:
    DCOT = "dcot"
    COT = "cot"


class DataProcessor:

    def __init__(
        self,
        dataset_path,
        mode=DataProcessorMode.DCOT,
        eos="</s>",
        epochs=1,
        seed=42,
        chat_format=None,
    ):
        random.seed(seed)
        with open(dataset_path, "r", encoding="utf-8") as f:
            self.raw_dataset = json.load(f)

        if mode == DataProcessorMode.DCOT:
            print("DCoT Data")
            self.ccot_dataset = self.create_ccot_dataset(
                self.raw_dataset, eos, epochs, chat_format
            )
        elif mode == DataProcessorMode.COT:
            print("CoT Data")
            self.ccot_dataset = self.create_cot_dataset(
                self.raw_dataset, eos, epochs, chat_format
            )
        else:
            raise ValueError(
                "Invalid mode. Choose from 'dcot', 'cot'"
            )

    def get_hf_dataset(self):
        """
        Returns the CCOT dataset in a format compatible with the Hugging Face library.

        Returns:
            list: The CCOT dataset.

        """
        prompts, responses = zip(
            *[(data["prompt"], data["response"]) for data in self.ccot_dataset]
        )
        hf_dataset = Dataset.from_dict({"prompt": prompts, "response": responses})
        hf_dataset = hf_dataset.map(
            lambda examples: {
                "text": [
                    prompt + response
                    for prompt, response in zip(
                        examples["prompt"], examples["response"]
                    )
                ]
            },
            batched=True,
        )

        return hf_dataset

    def create_ccot_dataset(self, dataset, eos, epochs, chat_format):
        ccot_dataset = []
        for _ in range(epochs):
            epoch_samples = []
            for x in dataset:
                list_cots = [cot["cot"] for cot in x["correct_cots"]]
                ccot_pairs = self.get_permutations(list_cots)
                for ccot in ccot_pairs:
                    question = x["question"]
                    context = None if "context" not in x else x["context"]
                    options = None if "options" not in x else x["options"]
                    answer = x["answer"]
                    data_point = self.create_ccot_data_point(
                        question, context, options, ccot, answer, eos, chat_format
                    )
                    epoch_samples.append(data_point)
            random.shuffle(epoch_samples)
            ccot_dataset.extend(epoch_samples)
        return ccot_dataset

    def create_cot_dataset(self, dataset, eos, epochs, chat_format):
        cot_dataset = []
        for e in range(epochs):
            epoch_samples = []
            for x in dataset:
                for cot in x["correct_cots"]:
                    question = x["question"]
                    context = None if "context" not in x else x["context"]
                    options = None if "options" not in x else x["options"]
                    answer = x["answer"]
                    data_point = self.create_ccot_data_point(
                        question,
                        context,
                        options,
                        [cot["cot"]],
                        answer,
                        eos,
                        chat_format,
                    )
                    epoch_samples.append(data_point)
            random.shuffle(epoch_samples)
            cot_dataset.extend(epoch_samples)
        return cot_dataset

    def create_monotonous_cot_dataset(self, dataset, eos, epochs, chat_format):
        cot_dataset = []
        for e in range(epochs):
            epoch_samples = []
            for x in dataset:
                # pick 1 random cot and using that cot for all the questions
                # in this way we keep the same amount of data
                # and we can train the model on only 1 cot / question
                if len(x["correct_cots"]) >= 1:
                    cot = random.choice(x["correct_cots"])
                    for _ in x["correct_cots"]:
                        question = x["question"]
                        context = None if "context" not in x else x["context"]
                        options = None if "options" not in x else x["options"]
                        answer = x["answer"]
                        data_point = self.create_ccot_data_point(
                            question,
                            context,
                            options,
                            [cot["cot"]],
                            answer,
                            eos,
                            chat_format,
                        )
                        epoch_samples.append(data_point)
            random.shuffle(epoch_samples)
            cot_dataset.extend(epoch_samples)
        return cot_dataset

    def create_ccot_data_point(
        self, question, context, options, list_cots, answer, eos, chat_format
    ):
        # prepare prompt
        prompt = str(
            Prompt(
                question=question,
                k=len(list_cots),
                context=context,
                options=options,
                chat_format=chat_format,
            )
        )
        # prepare response
        response = self.create_response(list_cots, answer, eos)
        return {"prompt": prompt, "response": response}

    def create_response(self, list_cots, answer, eos):
        ccot = ""
        for i, cot in enumerate(list_cots):
            if i == 0:
                ccot += f"{cot}\n"
            else:
                ccot += f"[Answer {i+1}] {cot}\n"
        ccot += f"\n[Final answer] {answer} {eos}"
        return ccot

    @staticmethod
    def get_permutations(l):
        list_permutations = []
        for i in range(1, len(l) + 1):
            sample = random.sample(list(permutations(l, i)), 1)
            list_permutations.extend((sample))
        return list_permutations