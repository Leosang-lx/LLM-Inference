import time
import torch.nn as nn
import torch
from tqdm import tqdm
from transformers import GPT2LMHeadModel, BertTokenizer, GPT2Config
from transformers import AutoModel, AutoTokenizer, AutoConfig
from sampling import apply_sampling
import os


def check_files_exist(model_directory):
    required_files = {
        'config.json': False,
        'pytorch_model.bin': False,  # 或者是 model.bin 或其他模型权重文件名
        'special_tokens_map.json': False,
        'tokenizer_config.json': False,
        'vocab.txt': False,  # 或者其他词汇表文件名
    }
    # 检查所有必要的文件是否都存在
    for filename in required_files.keys():
        filepath = os.path.join(model_directory, filename)
        if os.path.exists(filepath):
            required_files[filename] = True
        else:
            print(f"Missing required file: {filepath}")

    return all(required_files.values())


def load_pretrained_local(model_dir):
    config = AutoConfig.from_pretrained(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModel.from_pretrained(model_dir)

    return config, tokenizer, model


# load pre-trained model, tokenizer and configuration of GPT-2
model_tag = "uer/gpt2-chinese-cluecorpussmall"
developer_name, model_name = tuple(model_tag.split('/'))
cache_path = "model_file"
model_path = f'{cache_path}/models--{developer_name}--{model_name}/snapshots/c2c0249d8a2731f269414cc3b22dff021f8e07a3'

# 检查模型文件是否完整
if check_files_exist(model_path):
    print("All required files are present.")
else:
    print("Some required files are missing.")

# config = GPT2Config.from_pretrained(model_path)
config = AutoConfig.from_pretrained(model_path)
model_config = (
config.vocab_size, config.n_positions, config.n_layer, config.n_embd, config.n_head, config.n_embd // config.n_head, 4)
print(config)

# tokenizer = BertTokenizer.from_pretrained(model_tag, cache_dir=cache_path)
# model = GPT2LMHeadModel.from_pretrained(model_tag, cache_dir=cache_path).to("cuda")
# device = 'cuda' if torch.cuda.is_available() else 'cpu'
device = 'cpu'
print(f'Device={device}')
model = GPT2LMHeadModel.from_pretrained(model_path).to(device)
# model = AutoModel.from_pretrained(model_path).to(device)
model.eval()

# tokenizer = BertTokenizer.from_pretrained(model_path)
tokenizer = AutoTokenizer.from_pretrained(model_path)


if __name__ == '__main__':
    # 输入文本
    # 101 tokens
    text = "在一个风和日丽的下午，小镇的街道上人来人往，孩子们在巷口追逐嬉戏。李阿姨拿着刚从市场买回来的菜篮子，步履轻盈地走回家。街边的老槐树下，几位老人正围坐在一起下象棋，不时传来欢声笑语。今天是不是一个好日子？"
    # 5 tokens
    # text = "明天降温了"
    print('Input length:', len(text))

    batch_size = 1
    input_ids = torch.LongTensor([tokenizer.convert_tokens_to_ids(list(text))]).to(device)
    # input_ids = tokenizer.encode(text, return_tensors='pt').to('cuda')  # 将文本编码为ID

    # KV-cache for the inference request
    past_key_values = None
    use_cache = True
    do_sample = False
    top_k = 20
    top_p = 0.6
    print(f'use_kv_cache={use_cache}')
    print(f'do_sample={do_sample}')

    # token generation
    generated_text = text
    max_length = 200  # limit length
    print('Max length:', max_length)

    token_generation_latency = []
    start = time.perf_counter()
    start_decoding = None
    initial_input_len = len(text)
    for i in tqdm(range(initial_input_len, max_length)):
        with torch.no_grad():
            # forward with necessary input tokens
            outputs = model(input_ids, use_cache=use_cache, past_key_values=past_key_values)

            # output logits: (batch, sequence, vocab_size)
            logits = outputs.logits
            logits_new_token = logits[:, -1, :]  # (batch, vocab_size)

            # generate the next token based on the predicted logits
            if do_sample:
                # topk & topp sampling
                next_tokens = apply_sampling(logits_new_token, top_k, top_p)
            else:
                # greedy search with the maximum probability
                next_tokens = torch.argmax(logits_new_token, dim=-1).unsqueeze(-1)

            # input_ids: for the i^th round of token generation, it only input with the latest token and past KV-cache
            if use_cache:
                # only require the last token for decoding phase
                input_ids = next_tokens
                # obtain past key_values from model outputs
                past_key_values = outputs.past_key_values
            else:
                # concat the generated token to the existing sequence
                input_ids = torch.concat((input_ids, next_tokens), dim=-1)

            # add the new token to the text sequence
            if batch_size == 1:
                new_tokens = tokenizer.convert_ids_to_tokens(next_tokens)  # skip_special_tokens=True when necessary
                # print(new_tokens)
                generated_text += new_tokens[-1]

                # stop generation when meeting the [EOS] token
                if tokenizer.eos_token_id == int(next_tokens[0, 0]):
                    break
            if i == initial_input_len:
                start_decoding = time.perf_counter()

    end = time.perf_counter()
    consumption = end - start
    prefill_latency = start_decoding - start
    decoding_latency = end - start_decoding
    print("Generated text:", generated_text)
    print('Generated length:', len(generated_text))
    print(f'Generation latency: {consumption}s')
    print(f'Prefill latency: {prefill_latency}s')
    print(f'Decoding latency: {decoding_latency}s')
