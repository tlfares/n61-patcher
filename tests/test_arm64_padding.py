"""Offline relocation checks for explicitly audited ARM64 alignment padding."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'patches/impl/common'),
                str(ROOT / 'patches/impl/kc/sn2400')]
from port import instructions, relocate_code


def words(*values):
    return struct.pack('<' + 'I' * len(values), *values)


class PaddingTests(unittest.TestCase):
    def test_invalid_instruction_still_fails(self):
        with self.assertRaises(ValueError):
            instructions(words(0x14000002, 0xffffffff, 0xd65f03c0), 0x1000)

    def test_audited_unreachable_zero_is_preserved(self):
        raw = words(0x14000002, 0, 0xd65f03c0)
        out, refs = relocate_code(raw, 0x1000, lambda a: a + 0x1000,
                                  padding_words=(0x1004,))
        self.assertEqual(out, raw)
        self.assertEqual(refs, [{'kind': 'b', 'pc': 0x1000,
                                 'old': 0x1008, 'new': 0x2008}])

    def test_fallthrough_into_padding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'fallthrough'):
            instructions(words(0xd503201f, 0, 0xd65f03c0), 0x1000,
                         padding_words=(0x1004,))

    def test_direct_branch_into_padding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'branch into'):
            instructions(words(0x14000002, 0xd65f03c0, 0), 0x1000,
                         padding_words=(0x1008,))

    def test_nonzero_or_out_of_range_padding_is_rejected(self):
        for raw, address in [(words(0xd65f03c0, 0xd503201f), 0x1004),
                             (words(0xd65f03c0), 0x2000)]:
            with self.subTest(address=address), self.assertRaises(ValueError):
                instructions(raw, 0x1000, padding_words=(address,))


if __name__ == '__main__':
    unittest.main()
