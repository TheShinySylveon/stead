import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="fixture")
    parser.add_argument("--count", action="store_true", help="print a count")
    return parser
