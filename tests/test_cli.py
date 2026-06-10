import unittest

from cheatpilot.__main__ import build_parser


class CliParserTest(unittest.TestCase):
    def test_interactive_flag_is_supported(self) -> None:
        args = build_parser().parse_args(["--interactive"])

        self.assertTrue(args.interactive)

    def test_message_arguments_still_work(self) -> None:
        args = build_parser().parse_args(["打开", "game.exe"])

        self.assertEqual(args.message, ["打开", "game.exe"])
        self.assertFalse(args.interactive)


if __name__ == "__main__":
    unittest.main()
