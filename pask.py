#!/usr/bin/env python3
"""
pask - 论文提问助手
监听Windows剪贴板，自动向AI提问论文相关问题
"""

import os
import sys
import json
import argparse
import time
import threading
from anthropic import Anthropic
from rich.console import Console
from rich.markdown import Markdown

# 初始化 rich console
console = Console()

# ------------------------
# 路径
# ------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
MODEL_DIR = os.path.expanduser("~/.anthropic_llm_profiles")

# 全局控制变量
pause_event = threading.Event()
pause_event.set()  # 初始为未暂停
running = True

# 视觉分隔符
SEPARATOR = "=" * 80


# ------------------------
# 终端输出工具
# ------------------------
def print_header(text):
    """打印带样式的标题"""
    print(f"\n{SEPARATOR}")
    print(f"🔹 {text}")
    print(f"{SEPARATOR}\n")


def print_section(text):
    """打印小节标题"""
    print(f"\n▶ {text}\n")


def print_success(text):
    """打印成功消息"""
    print(f"✅ {text}")


def print_error(text):
    """打印错误消息"""
    print(f"❌ {text}")


def print_warning(text):
    """打印警告消息"""
    print(f"⚠️  {text}")


def print_info(text):
    """打印信息消息"""
    print(f"ℹ️  {text}")


# ------------------------
# 配置
# ------------------------
def load_config():
    """加载配置，如果不存在则返回默认配置"""
    if not os.path.exists(CONFIG_FILE):
        return {"system_prompt": [], "sum_model": "", "ask_model": "", "ask_prompt": ""}

    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(config):
    """保存配置"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


# ------------------------
# 模型管理
# ------------------------
def get_all_models():
    """获取所有可用模型"""
    if not os.path.exists(MODEL_DIR):
        return []
    return [f[:-3] for f in os.listdir(MODEL_DIR) if f.endswith(".sh")]


def list_models():
    """列出所有可用模型"""
    models = get_all_models()
    if not models:
        print_warning("没有可用模型")
        return

    print_header("可用模型列表")
    for i, m in enumerate(models, 1):
        print(f"  {i}. {m}")


def load_model(model_name):
    """加载指定模型的配置"""
    path = os.path.join(MODEL_DIR, f"{model_name}.sh")

    if not os.path.exists(path):
        print_error(f"模型不存在: {model_name}")
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
# Markdown 文件处理
# ------------------------
def validate_and_parse_md(md_path):
    """验证并解析MD文件，提取论文标题和内容"""
    print_section(f"正在读取文件: {md_path}")

    if not os.path.exists(md_path):
        print_error(f"文件不存在: {md_path}")
        sys.exit(1)

    if not md_path.endswith('.md'):
        print_warning("文件扩展名不是.md，请确认是Markdown文件")

    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.split('\n')
        first_line = lines[0].strip()
        second_line = lines[1].strip() if len(lines) > 1 else ""

    print_info(f"第一行: {first_line}")

    # 检查格式：一级标题以"总结分析"结尾
    if not first_line.startswith('# '):
        print_error("文件格式错误：第一行必须是一级标题（以# 开头）")
        print("  正确格式示例: # Attention Is All You Need 总结分析")
        sys.exit(1)

    if not first_line.endswith('总结分析'):
        print_warning("一级标题应以'总结分析'结尾，格式可能不正确")
        print(f"  当前标题: {first_line}")

    # 提取论文标题（去除# 和末尾的"总结分析"）
    title_with_suffix = first_line[2:].strip()  # 去掉 "# "
    if title_with_suffix.endswith('总结分析'):
        paper_title = title_with_suffix[:-4].strip()  # 去掉 "总结分析"
    else:
        paper_title = title_with_suffix
        print_warning("标题不以'总结分析'结尾，使用完整标题")

    print_success(f"论文标题: {paper_title}")
    print_success(f"已读取论文内容 ({len(content)} 字符)")

    # 验证分隔线
    if second_line.strip():
        print_info("检测到第二行内容（可能包含摘要或元数据）")

    return paper_title, content


# ------------------------
# 剪贴板监听
# ------------------------
def get_clipboard_content():
    """从Windows剪贴板获取内容（WSL环境）"""
    try:
        # 使用powershell获取剪贴板内容
        result = os.popen('powershell.exe -command "Get-Clipboard"').read()
        return result.strip() if result else ""
    except Exception as e:
        print_error(f"获取剪贴板失败: {e}")
        return ""


def clear_clipboard():
    """清空Windows剪贴板（WSL环境）"""
    try:
        os.system('powershell.exe -command "Set-Clipboard \'\'" 2>/dev/null')
    except Exception as e:
        print_error(f"清空剪贴板失败: {e}")


def clipboard_monitor_loop(prompt_text, model_config, system_prompt, paper_content):
    """剪贴板监听循环"""
    global running
    last_content = ""

    print_header("剪贴板监听已启动")
    print_info("操作提示:")
    print("  • 在Windows中复制内容即可自动发送给AI")
    print("  • 输入 'p' 或 'pause' 暂停监听")
    print("  • 输入 'r' 或 'resume' 恢复监听")
    print("  • 按 Ctrl+C 退出程序")
    print()

    print_section("等待剪贴板更新...")

    # 清空剪贴板
    print_info("正在清空剪贴板...")
    clear_clipboard()
    print_success("剪贴板已清空\n")

    while running:
        # 检查暂停状态
        while not pause_event.is_set():
            if not running:
                break
            time.sleep(0.1)

        if not running:
            break

        try:
            # 检查剪贴板内容
            current_content = get_clipboard_content()

            # 检查是否有新内容
            if current_content and current_content != last_content:
                last_content = current_content

                print_header(f"📋 检测到新内容 ({len(current_content)} 字符)")
                print(f"剪贴板内容预览:")
                preview = current_content[:200] + "..." if len(current_content) > 200 else current_content
                print(f"  {preview}")
                print()

                # 发送给AI
                send_to_ai(current_content, prompt_text, model_config, system_prompt, paper_content)

                print_section("等待剪贴板更新...")

        except KeyboardInterrupt:
            print("\n")
            print_warning("收到中断信号")
            break
        except Exception as e:
            print_error(f"监听出错: {e}")
            print_section("继续监听...")

        time.sleep(1)  # 每秒检查一次


def input_listener():
    """监听用户输入"""
    global running

    print_info("输入监听线程已启动，等待指令...")

    while running:
        try:
            # 使用非阻塞方式读取输入
            import select
            import sys

            # 检查是否有输入可用
            if select.select([sys.stdin], [], [], 0.1)[0]:
                cmd = sys.stdin.readline().strip().lower()

                if not cmd:
                    continue

                print(f"\n{SEPARATOR}")
                print(f"🔧 收到指令: {cmd}")
                print(f"{SEPARATOR}\n")

                if cmd in ['p', 'pause']:
                    if pause_event.is_set():
                        pause_event.clear()
                        print_warning("⏸️  监听已暂停")
                        print("  输入 'r' 或 'resume' 恢复")
                        print("  按 Ctrl+C 退出\n")
                    else:
                        print_info("监听已经是暂停状态")

                elif cmd in ['r', 'resume']:
                    if not pause_event.is_set():
                        pause_event.set()
                        print_success("▶️  监听已恢复")
                        print_section("等待剪贴板更新...")
                    else:
                        print_info("监听已经是运行状态")

                else:
                    print_warning(f"未知指令: {cmd}")
                    print("可用指令: pause(p), resume(r)")

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print_error(f"输入监听出错: {e}")


# ------------------------
# AI 交互
# ------------------------
def extract_text_from_response(message):
    """从AI响应中提取文本"""
    result = []

    for block in message.content:
        # 兼容 TextBlock
        if hasattr(block, "text"):
            result.append(block.text)

        # 有些实现可能是 dict
        elif isinstance(block, dict) and block.get("type") == "text":
            result.append(block.get("text", ""))

    return "\n".join(result)


def send_to_ai(content, prompt_template, model_config, system_prompt, paper_content):
    """发送问题给AI并流式输出答案"""
    print_section(f"🤖 正在使用模型 {model_config['model']} 回答...")

    # 组合prompt：论文内容 + 提问模板 + 问题
    full_prompt = f"【论文总结内容】\n{paper_content}\n\n {prompt_template}\n\n【问题对象】\n{content}"

    try:
        client = Anthropic(
            api_key=model_config['api_key'],
            base_url=model_config['base_url']
        )

        print_header("📝 AI 回答（流式）")

        # 流式输出同时收集完整文本
        full_response = ""
        with client.messages.create(
            model=model_config['model'],
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": full_prompt}
            ],
            stream=True
        ) as stream:
            for chunk in stream:
                if chunk.type == "content_block_delta":
                    if hasattr(chunk.delta, 'text'):
                        text = chunk.delta.text
                        print(text, end='', flush=True)
                        full_response += text

        # 流式输出完成后，格式化显示
        print(f"\n\n{SEPARATOR}")
        print_header("📝 AI 回答（格式化）")
        md = Markdown(full_response)
        console.print(md)
        print(f"\n{SEPARATOR}")

    except Exception as e:
        print_error(f"AI调用失败: {e}")


# ------------------------
# CLI 主逻辑
# ------------------------
def main():
    parser = argparse.ArgumentParser(
        description="📝 论文提问助手 - 监听剪贴板自动向AI提问",
        prog="pask",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  pask run paper.md          # 使用指定论文启动监听
  pask model list            # 列出可用模型
  pask model set deepseek    # 设置默认模型
  pask model current         # 查看当前模型

运行时指令:
  pause / p                  # 暂停监听
  resume / r                 # 恢复监听
  Ctrl+C                     # 退出程序
        """
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
    run_parser = subparsers.add_parser("run", help="启动监听")
    run_parser.add_argument("md_file", help="论文总结MD文件路径")

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
            config["ask_model"] = args.name
            save_config(config)
            print_success(f"提问模型已设置为: {args.name}")

        elif args.model_cmd == "current":
            m = config.get("ask_model")
            if m:
                print(f"📌 当前提问模型: {m}")
            else:
                print_warning("未设置提问模型")

        else:
            model_parser.print_help()

        return

    # ------------------------
    # run 逻辑
    # ------------------------
    if args.command == "run":
        print_header("PASK - 论文提问助手")
        print("版本: 1.0.0")
        print("监听Windows剪贴板，自动向AI提问论文相关问题\n")

        # 验证并解析MD文件，获取标题和内容
        paper_title, paper_content = validate_and_parse_md(args.md_file)

        # 检查模型
        model_name = config.get("ask_model")
        if not model_name:
            print_error("未设置提问模型")
            print_info("请先执行: pask model set deepseek")
            sys.exit(1)

        model_config = load_model(model_name)
        print_success(f"已加载模型: {model_name} ({model_config['model']})")

        # 获取prompt
        ask_prompt = config.get("ask_prompt", "")
        if not ask_prompt:
            ask_prompt = "请根据上面的论文总结内容回答问题："
            print_warning("未配置提问prompt，使用默认prompt")
        else:
            print_success(f"已加载提问prompt")

        # 获取系统prompt
        system_prompt = config.get("system_prompt", "")
        if isinstance(system_prompt, list):
            system_prompt = "\n".join(system_prompt)

        # 输出启动信息
        print(f"\n{SEPARATOR}")
        print(f"✅ 已经读入 [{paper_title}] ，agent启动")
        print(f"{SEPARATOR}\n")

        print_info("配置信息:")
        print(f"  论文文件: {args.md_file}")
        print(f"  论文标题: {paper_title}")
        print(f"  论文内容: {len(paper_content)} 字符")
        print(f"  使用模型: {model_name}")
        print(f"  提问prompt: {ask_prompt[:50]}..." if len(ask_prompt) > 50 else f"  提问prompt: {ask_prompt}")
        print()

        # 启动输入监听线程
        input_thread = threading.Thread(target=input_listener, daemon=True)
        input_thread.start()

        # 启动剪贴板监听
        clipboard_monitor_loop(ask_prompt, model_config, system_prompt, paper_content)

        print_header("程序已退出")
        print_success("感谢使用！")


if __name__ == "__main__":
    main()
