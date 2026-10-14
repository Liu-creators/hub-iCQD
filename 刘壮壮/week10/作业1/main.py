import argparse

from translator import translate
from translator.client import setup_client


def main() -> None:
    parser = argparse.ArgumentParser(description="中英翻译：单 agent 或多 agent")
    parser.add_argument("text", nargs="?", default="Hello, how are you?")
    parser.add_argument("--mode", choices=("single", "multi"), default="single")
    args = parser.parse_args()
    setup_client()
    print(translate(args.text, mode=args.mode))


if __name__ == "__main__":
    main()
