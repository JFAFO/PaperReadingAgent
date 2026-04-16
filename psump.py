#!/usr/bin/env python3
import os
import sys
import json
import argparse
from pypdf import PdfReader
from anthropic import Anthropic

# ------------------------
# 路径
# ------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MODEL_DIR = os.path.expanduser("~/.anthropic_llm_profiles")


# ------------------------
# 配置
# ------------------------
def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"system_prompt": ""}

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ------------------------
# 模型管理
# ------------------------
def get_all_models():
    if not os.path.exists(MODEL_DIR):
        return []
    return [f[:-3] for f in os.listdir(MODEL_DIR) if f.endswith(".sh")]


def list_models():
    models = get_all_models()
    if not models:
        print("⚠️ 没有可用模型")
        return

    print("📦 可用模型:")
    for m in models:
        print(f"  - {m}")


def load_model(model_name):
    path = os.path.join(MODEL_DIR, f"{model_name}.sh")

    if not os.path.exists(path):
        print(f"❌ 模型不存在: {model_name}")
        sys.exit(1)

    env = {}

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("export"):
                try:
                    _, rest = line.split("export", 1)
                    key, value = rest.strip().split("=", 1)
                    env[key.strip()] = value.strip()
                except:
                    continue

    return {
        "api_key": env.get("ANTHROPIC_AUTH_TOKEN"),
        "base_url": env.get("ANTHROPIC_BASE_URL"),
        "model": env.get("ANTHROPIC_MODEL"),
    }


# ------------------------
# PDF
# ------------------------
def extract_text_from_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"❌ 文件不存在: {pdf_path}")
        sys.exit(1)

    reader = PdfReader(pdf_path)
    text = ""

    for page in reader.pages:
        t = page.extract_text()
        if t:
            text += t + "\n"

    if len(text.strip()) < 50:
        print("❌ PDF 可能是扫描件，请先 OCR")
        sys.exit(1)

    return text


# ------------------------
# LLM
# ------------------------
def call_llm(text, config, model_config):
    print(f"⏳ 使用模型 {model_config['model']} 处理中...")

    client = Anthropic(
        api_key=model_config['api_key'],
        base_url=model_config['base_url']
    )

    # 系统提示词（角色设定）
    system_prompt = config.get("system_prompt", "你是一个专业的论文分析助手。")
    if isinstance(system_prompt, list):
        system_prompt = "\n".join(system_prompt)

    # 总结提示词（具体指令）
    sum_prompt = config.get("sum_prompt", "请总结这篇论文的核心内容。")
    if isinstance(sum_prompt, list):
        sum_prompt = "\n".join(sum_prompt)

    # 组合用户消息
    user_message = f"{sum_prompt}\n\n以下是论文文本：\n\n{text}"

    message = client.messages.create(
        model=model_config['model'],
        max_tokens=4096,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )
    def extract_text_from_response(message):
        result = []

        for block in message.content:
            # 兼容 TextBlock
            if hasattr(block, "text"):
                result.append(block.text)

            # 有些实现可能是 dict
            elif isinstance(block, dict) and block.get("type") == "text":
                result.append(block.get("text", ""))

        return "\n".join(result)
    # print("DEBUG content:", message.content)
    return extract_text_from_response(message)


# ------------------------
# CLI 主逻辑
# ------------------------
def main():
    parser = argparse.ArgumentParser(
        description="📄 PDF → Markdown LLM 工具",
        prog="psum"
    )

    subparsers = parser.add_subparsers(dest="command")

    # ------------------------
    # model 子命令
    # ------------------------
    model_parser = subparsers.add_parser("model", help="模型管理")
    model_sub = model_parser.add_subparsers(dest="model_cmd")

    model_sub.add_parser("list", help="列出模型")

    set_parser = model_sub.add_parser("set", help="设置默认模型")
    set_parser.add_argument("name")

    model_sub.add_parser("current", help="查看当前模型")

    # ------------------------
    # run 子命令
    # ------------------------
    run_parser = subparsers.add_parser("run", help="处理 PDF")
    run_parser.add_argument("input", help="PDF 文件")
    run_parser.add_argument("-o", "--output", help="输出 MD 文件")

    args = parser.parse_args()
    config = load_config()

    # ------------------------
    # 无命令 → 显示帮助
    # ------------------------
    if not args.command:
        parser.print_help()
        return

    # ------------------------
    # model 逻辑
    # ------------------------
    if args.command == "model":
        if args.model_cmd == "list":
            list_models()

        elif args.model_cmd == "set":
            load_model(args.name)  # 校验存在
            config["sum_model"] = args.name
            save_config(config)
            print(f"💾 默认模型已设置为: {args.name}")

        elif args.model_cmd == "current":
            m = config.get("sum_model")
            if m:
                print(f"📌 当前模型: {m}")
            else:
                print("⚠️ 未设置默认模型")

        else:
            model_parser.print_help()

        return

    # ------------------------
    # run 逻辑
    # ------------------------
    if args.command == "run":
        model_name = config.get("sum_model")

        if not model_name:
            print("❌ 未设置默认模型")
            print("👉 请先执行: script.py model set deepseek")
            sys.exit(1)

        model_config = load_model(model_name)

        output_path = args.output or os.path.splitext(args.input)[0] + " 总结" + ".md"

        text = extract_text_from_pdf(args.input)
        print(f"✅ 提取完成 ({len(text)} 字符)")

        result = call_llm(text, config, model_config)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)

        print(f"🚀 完成: {output_path}")



if __name__ == "__main__":
    main()