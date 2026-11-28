"""HWP 3.0(한글 3.x·96·97) 독립 판독기 — 검증서가 옛 형식 원본도 직접 읽어 변환본과 대조하도록 한다.

변환 엔진(rhwp)과 별개 코드다. 파일 구조는 한글과컴퓨터 공개 문서 「한글 문서 파일 형식 3.0」과
LibreOffice hwpfilter(MPL-2.0)의 읽기 순서를 따라 새로 썼고, 글자 부호 표(옛한글 자모·특수 문자)는
hwpfilter 의 hcode.cxx 값을 옮겼다. 읽는 것: 글, 표(셀 병합), 글상자, 수식, 그림(이름·내장 데이터),
각주·미주, 머리말·꼬리말, 캡션, 자동 번호. 읽지 않는 것: 글자·문단 모양(검증서는 내용만 본다).
"""
from __future__ import annotations

import os
import re
import struct
import zlib

from .model import Document, Paragraph, Table, Cell, Image, Equation, Note, TextBox, HeaderFooter

AUTONUM_MARK = "⁣"
SIGNATURES = (b"HWP Document File V3.00", b"HWP Document File V2.10", b"HWP Document File V2.00")
V1_PREFIX = b"HWP Document File V1."
ID_LEN, INFO_LEN, SUMMARY_LEN = 30, 128, 9 * 56 * 2
CSHAPE, PSHAPE, LINEINFO, CELL = 31, 187, 14, 27
MAX_DEPTH = 64
WSIZE = [1, 4, 4, 4, 4, 4, 4, 42, 48, 4, 4, 4, 4, 1, 4, 4, 4, 4, 4, 4, 4, 4, 12, 5, 3, 3, 123, 4, 32, 4, 2, 2]
SKIP_BLOCK = {0, 1, 2, 3, 4, 12, 27, 29}

JAMO=[12593, 12594, 12595, 12596, 12597, 12598, 12599, 12600, 12601, 12602, 12603, 12604, 12605, 12606, 12607, 12608, 12609, 12610, 12611, 12612, 12613, 12614, 12615, 12616, 12617, 12618, 12619, 12620, 12621, 12622, 12658, 12659, 12662, 12666, 12668, 12669, 12670, 12677, 12664, 12671, 12673, 12653, 4547, 4548, 4371, 4372, 4373, 4374, 4551, 4552, 4553, 4554, 4555, 4556, 4557, 4558, 4559, 4560, 4561, 4562, 4563, 4564, 4565, 4566, 4567, 4568, 4379, 4570, 4571, 4572, 4573, 4574, 4575, 4576, 4577, 4578, 4383, 4579, 4386, 4387, 4388, 4389, 4390, 4392, 4393, 4394, 4581, 4396, 4398, 4400, 4401, 4403, 4404, 4405, 4407, 4408, 4409, 4410, 4411, 4412, 4413, 4414, 4415, 4417, 4589, 4418, 4419, 4420, 4421, 4422, 4423, 4424, 4425, 4591, 4426, 4427, 4593, 4594, 4429, 4430, 4431, 4432, 4433, 4434, 4435, 4436, 4437, 4438, 4439, 4597, 4598, 4599, 4600, 4601, 4470, 4471, 4472, 4473, 4474, 4475, 4476, 4477, 4478, 4479, 4480, 4481, 4482, 4483, 4484, 4485, 4486, 4487, 4489, 4490, 4491, 4492, 4493, 4494, 4495, 4496, 4498, 4499, 4501, 4502, 4503, 4504, 4505, 4506, 4507, 4508, 4509, 4511, 4512, 4514, 4520, 4521, 4522, 4523, 4524, 4525, 4526, 4356, 4527, 4528, 4529, 4530, 4531, 4532, 4533, 4534, 4535, 4536, 4360, 4537, 4538, 4539, 4540, 4541, 12617, 4542, 4543, 4544, 4545, 4546, 4382, 4384, 4391, 4583, 4584, 4586, 4406, 4440, 4582, 4587, 4592, 4569, 4547, 4548, 4549, 4372, 4550, 4374, 4551, 4552, 4553, 4554, 4555, 12649, 4557, 4558, 4559, 4377, 4561, 4562, 4563, 4564, 4565, 4566, 4567, 4568, 4379, 4570, 4571, 4572, 4573, 4574, 4575, 4576, 4577, 4578, 4383, 4579, 4386, 4387, 4388, 4389, 4390, 4392, 4393, 4580, 4581, 4396, 4398, 4400, 4401, 4403, 4404, 4405, 4407, 4408, 4409, 4410, 4411, 4412, 4413, 4414, 4415, 4588, 4589, 4418, 4419, 4420, 4421, 4422, 4423, 4424, 4425, 4591, 4426, 4427, 4593, 4594, 4429, 4430, 4431, 4432, 4433, 4434, 4435, 4436, 4437, 4438, 4439, 4597, 4598, 4599, 4600, 4601]
JAMOCOMP=[(4352, 4449, 4583), (4352, 4449, 12647), (4352, 4449, 4573), (4352, 4449, 4578), (4352, 4449, 4581), (4352, 4449, 4593), (4352, 4451, 4578), (4352, 4451, 4601), (4352, 4453, 4583), (4352, 4453, 4551), (4352, 4453, 4573), (4352, 4453, 4578), (4352, 4453, 4579), (4352, 4455, 4583), (4352, 4455, 4593), (4352, 4455, 4601), (4352, 4457, 4566), (4352, 4457, 4573), (4352, 4457, 4578), (4352, 4457, 4593), (4352, 4457, 4599), (4352, 4457, 4600), (4352, 4458, 4601), (4352, 4461, 4578), (4352, 4462, 4551), (4352, 4462, 4557), (4352, 4462, 4570), (4352, 4462, 4573), (4352, 4462, 4578), (4352, 4462, 4598), (4352, 4462, 4601), (4352, 4463, 4551), (4352, 4463, 4601), (4352, 4466, 4578), (4352, 4466, 4601), (4352, 4467, 4551), (4352, 4467, 4573), (4352, 4467, 4575), (4352, 4467, 4578), (4352, 4467, 4601), (4352, 4468, 4601), (4352, 4469, 4583), (4352, 4469, 4557), (4352, 4469, 4578), (4352, 4469, 4601), (4352, 4497, 4601), (4352, 4510, 4583), (4352, 4510, 4563), (4352, 4510, 4565), (4352, 4510, 4579), (4352, 4513, 4593), (4352, 4470), (4352, 4472), (4352, 4476), (4352, 4476, 4523), (4352, 4476, 4527), (4352, 4476, 4535), (4352, 4489), (4352, 4489, 4523), (4352, 4489, 4540), (4352, 4491), (4352, 4491, 4523), (4352, 4492), (4352, 4493), (4352, 4498), (4352, 4498, 4540), (4352, 4501), (4352, 4502), (4352, 4504), (4352, 4507), (4352, 4508), (4352, 4509), (4352, 4511), (4352, 4511, 4540), (4353, 4451, 4578), (4353, 4453, 4588), (4353, 4453, 4589), (4353, 4462, 4578), (4353, 4466, 4578), (4353, 4469, 4578), (4353, 4469, 4601), (4353, 4497, 4540), (4353, 4470), (4353, 4475), (4353, 4489), (4353, 4492), (4353, 4504), (4354, 4449, 4583), (4354, 4449, 4548), (4354, 4449, 4570), (4354, 4449, 4573), (4354, 4449, 4578), (4354, 4449, 4601), (4354, 4453, 4571), (4354, 4453, 4573), (4354, 4453, 4579), (4354, 4455, 4549), (4354, 4455, 4551), (4354, 4455, 4601), (4354, 4457, 4578), (4354, 4457, 4580), (4354, 4457, 4595), (4354, 4462, 4550), (4354, 4462, 4551), (4354, 4462, 4552), (4354, 4462, 4573), (4354, 4462, 4578), (4354, 4462, 4597), (4354, 4466, 4578), (4354, 4467, 4547), (4354, 4469, 4547), (4354, 4469, 4573), (4354, 4469, 4578), (4354, 4510, 4567), (4354, 4470), (4354, 4476), (4354, 4476, 4520), (4354, 4492), (4354, 4502), (4354, 4503), (4354, 4504), (4354, 4507), (4355, 4449, 4583), (4355, 4449, 4551), (4355, 4449, 4377), (4355, 4449, 4571), (4355, 4449, 4573), (4355, 4449, 4578), (4355, 4449, 4593), (4355, 4449, 4601), (4355, 4451, 4578), (4355, 4451, 4593), (4355, 4453, 4573), (4355, 4455, 4601), (4355, 4457, 4583), (4355, 4457, 4566), (4355, 4457, 4578), (4355, 4457, 4593), (4355, 4461, 4578), (4355, 4462, 4558), (4355, 4462, 4377), (4355, 4462, 4570), (4355, 4462, 4578), (4355, 4466, 4578), (4355, 4467, 4557), (4355, 4467, 4558), (4355, 4467, 4578), (4355, 4467, 4579), (4355, 4467, 4593), (4355, 4468, 4601), (4355, 4469, 4601), (4355, 4510, 4583), (4355, 4510, 4584), (4355, 4510, 4586), (4355, 4510, 4547), (4355, 4510, 4556), (4355, 4510, 4579), (4355, 4510, 4585), (4355, 4470), (4355, 4472), (4355, 4476), (4355, 4476, 4535), (4355, 4489), (4355, 4489, 4523), (4355, 4492), (4355, 4501), (4355, 4502), (4355, 4504), (4355, 4505), (4355, 4505, 4523), (4355, 4505, 4540), (4356, 4449, 4568), (4356, 4449, 4578), (4356, 4449, 4601), (4356, 4451, 4578), (4356, 4457, 4578), (4356, 4457, 4601), (4356, 4461, 4578), (4356, 4462, 4578), (4356, 4462, 4601), (4356, 4466, 4578), (4356, 4467, 4578), (4356, 4469, 4601), (4356, 4475), (4356, 4492), (4356, 4504), (4357, 4449, 4583), (4357, 4449, 4573), (4357, 4449, 4578), (4357, 4449, 4597), (4357, 4449, 4601), (4357, 4451, 4578), (4357, 4455, 4551), (4357, 4455, 4578), (4357, 4455, 4601), (4357, 4457, 4573), (4357, 4457, 4578), (4357, 4457, 4593), (4357, 4461, 4573), (4357, 4461, 4578), (4357, 4462, 4573), (4357, 4462, 4578), (4357, 4466, 4578), (4357, 4467, 4573), (4357, 4467, 4578), (4357, 4469, 4573), (4357, 4469, 4578), (4357, 4469, 4601), (4357, 4510, 4567), (4357, 4510, 4572), (4357, 4510, 4573), (4357, 4470), (4357, 4472), (4357, 4474), (4357, 4475), (4357, 4486), (4357, 4487), (4357, 4492), (4357, 4501), (4357, 4502), (4357, 4504), (4357, 4505), (4357, 4505, 4540), (4357, 4507), (4378, 4451), (4378, 4451, 4540), (4358, 4449, 4584), (4358, 4449, 4551), (4358, 4449, 4557), (4358, 4449, 4377), (4358, 4449, 4568), (4358, 4449, 4578), (4358, 4451, 4578), (4358, 4453, 4550), (4358, 4453, 4601), (4358, 4457, 4550), (4358, 4457, 4573), (4358, 4457, 4578), (4358, 4461, 4578), (4358, 4462, 4583), (4358, 4462, 4551), (4358, 4462, 4578), (4358, 4462, 4588), (4358, 4462, 4589), (4358, 4462, 4601), (4358, 4463, 4601), (4358, 4467, 4583), (4358, 4468, 4601), (4358, 4469, 4583), (4358, 4469, 4598), (4358, 4469, 4601), (4358, 4510, 4547), (4358, 4470), (4358, 4472), (4358, 4476), (4358, 4476, 4527), (4358, 4482), (4358, 4483), (4358, 4492), (4358, 4502), (4358, 4502, 4535), (4358, 4504), (4358, 4511), (4358, 4511, 4523), (4358, 4511, 4540), (4359, 4449, 4583), (4359, 4449, 4553), (4359, 4449, 4573), (4359, 4449, 4578), (4359, 4449, 4579), (4359, 4449, 4593), (4359, 4449, 4598), (4359, 4449, 4601), (4359, 4453, 4551), (4359, 4455, 4593), (4359, 4457, 4583), (4359, 4457, 4573), (4359, 4457, 4578), (4359, 4461, 4578), (4359, 4462, 4583), (4359, 4462, 4551), (4359, 4462, 4377), (4359, 4462, 4561), (4359, 4462, 4562), (4359, 4462, 4578), (4359, 4462, 4591), (4359, 4462, 4601), (4359, 4463, 4601), (4359, 4467, 4583), (4359, 4467, 4547), (4359, 4469, 4583), (4359, 4469, 4578), (4359, 4469, 4593), (4359, 4469, 4601), (4359, 4510, 4547), (4359, 4510, 4565), (4359, 4510, 4579), (4359, 4513, 4593), (4359, 4470), (4359, 4471), (4359, 4472), (4359, 4476), (4359, 4476, 4520), (4359, 4476, 4527), (4359, 4476, 4535), (4359, 4476, 4540), (4359, 4482), (4359, 4492), (4359, 4502), (4359, 4504), (4359, 4506), (4359, 4511), (4359, 4511, 4523), (4359, 4511, 4540), (4360, 4449, 4578), (4360, 4455, 4601), (4360, 4457, 4578), (4360, 4462, 4578), (4360, 4468, 4601), (4360, 4469, 4601), (4385, 4458, 4601), (4385, 4510, 4429), (4385, 4492), (4385, 4504), (4361, 4449, 4554), (4361, 4449, 4573), (4361, 4449, 4578), (4361, 4449, 4593), (4361, 4449, 4601), (4361, 4451, 4578), (4361, 4451, 4593), (4361, 4453, 4583), (4361, 4453, 4547), (4361, 4453, 4588), (4361, 4453, 4589), (4361, 4455, 4583), (4361, 4455, 4565), (4361, 4455, 4573), (4361, 4455, 4579), (4361, 4455, 4593), (4361, 4455, 4601), (4361, 4457, 4551), (4361, 4457, 4578), (4361, 4458, 4601), (4361, 4459, 4601), (4361, 4461, 4578), (4361, 4461, 4593), (4361, 4462, 4583), (4361, 4462, 4578), (4361, 4462, 4601), (4361, 4466, 4578), (4361, 4467, 4578), (4361, 4467, 4579), (4361, 4467, 4593), (4361, 4468, 4601), (4361, 4469, 4551), (4361, 4469, 4558), (4361, 4469, 4570), (4361, 4469, 4578), (4361, 4469, 4601), (4361, 4497, 4601), (4361, 4510, 4554), (4361, 4510, 4566), (4361, 4510, 4593), (4361, 4510, 4579), (4361, 4513, 4573), (4361, 4513, 4593), (4361, 4470), (4361, 4471), (4361, 4472), (4361, 4476), (4361, 4476, 4520), (4361, 4476, 4527), (4361, 4476, 4535), (4361, 4476, 4540), (4361, 4478), (4361, 4489), (4361, 4489, 4523), (4361, 4492), (4361, 4496), (4361, 4498), (4361, 4498, 4540)]

_COMPAT_CHO = "\u3131\u3132\u3134\u3137\u3138\u3139\u3141\u3142\u3143\u3145\u3146\u3147\u3148\u3149\u314a\u314b\u314c\u314d\u314e"
CHO = [0x111e, 0, 0x1100, 0x1101, 0x1102, 0x1103, 0x1104, 0x1105, 0x1106, 0x1107, 0x1108, 0x1109, 0x110a, 0x110b, 0x110c, 0x110d,
       0x110e, 0x110f, 0x1110, 0x1111, 0x1112, 0x1120, 0x1121, 0x1127, 0x112b, 0x112d, 0x112f, 0x1132, 0x1136, 0x1140, 0x114c, 0x1158]
JUNG = [0, 0, 0, 0x1161, 0x1162, 0x1163, 0x1164, 0x1165, 0, 0, 0x1166, 0x1167, 0x1168, 0x1169, 0x116a, 0x116b,
        0, 0x1188, 0x116c, 0x116d, 0x116e, 0x116f, 0x1170, 0x1171, 0x1191, 0x1194, 0x1172, 0x1173, 0x1174, 0x1175, 0x119e, 0x11a1]
JONG = [0x11d9, 0, 0x11a8, 0x11a9, 0x11aa, 0x11ab, 0x11ac, 0x11ad, 0x11ae, 0x11af, 0x11b0, 0x11b1, 0x11b2, 0x11b3, 0x11b4, 0x11b5,
        0x11b6, 0x11b7, 0x11e6, 0x11b8, 0x11b9, 0x11ba, 0x11bb, 0x11bc, 0x11bd, 0x11be, 0x11bf, 0x11c0, 0x11c1, 0x11c2, 0x11eb, 0x11f0]
TG_KS = [0xC7D1, 0xB1DB, 0xB0FA, 0xC4C4, 0xC7BB, 0xC5CD, 0, 0, 0xA2B1, 0xA3DF, 0xA2D5, 0xA6B1, 0xA1B8, 0xA1B9, 0xA3DF, 0xA1DA,
         0xA2C6, 0xA2CC, 0xA2CB, 0, 0, 0xA6BE, 0xA6B9, 0xA6C1, 0xA6C2, 0xA6B4, 0xA6AD, 0xA6AF, 0xA6B0, 0xA6C3, 0xA6C4, 0,
         0xA6AE, 0xA6B0, 0xA2D7, 0xA1E1, 0xA1D6, 0, 0xA6BC, 0xA6B7, 0xA6B1, 0xA6AE, 0xA6B5, 0xA6B3, 0xA6B2, 0xA6AC, 0xA6B6, 0xA6BA,
         0xA6BF, 0xA6B8, 0xA6BD, 0xA6C5, 0xA6C6, 0xA6C8, 0xA6C7, 0xA6C0, 0xA6BB, 0, 0, 0, 0xA1E1, 0xA1E1, 0xA1E1, 0xA1E1]
EXTRA = {0x81: 0x201C, 0x82: 0x201D, 0x83: 0x2018, 0x84: 0x2019, 0x480: 0x2D0, 0x48A: 0x2DA, 0x1F2E: 0x306E,
         0x2010: 0x2010, 0x2013: 0x2013, 0x2014: 0x2014, 0x2015: 0x2015, 0x2022: 0x2022, 0x203B: 0x203B, 0x2051: 0xB1,
         0x2053: 0xD7, 0x2103: 0x2103, 0x2113: 0x2113, 0x2190: 0x2190, 0x2191: 0x2191, 0x2192: 0x2192, 0x2193: 0x2193,
         0x2219: 0x2219, 0x2223: 0x2223, 0x223C: 0x223C, 0x22C5: 0x22C5, 0x2024: 0x30FB, 0x2058: 0x25B3, 0x205A: 0x25CB,
         0x3151: 0x2027, 0x3157: 0x2027, 0x32B0: 0xFF70, 0x3404: 0x2024, 0x3441: 0x25A0, 0x3446: 0x2192, 0x3479: 0x25B7,
         0x347A: 0x25B6, 0x35E1: 0x2500, 0x37ED: 0x2550, 0x2F00: 0x25A1, 0x2F06: 0x25A0, 0x2F08: 0x25AA, 0x2F11: 0x25E6,
         0x2F14: 0x25E6, 0x2F17: 0x2022, 0x2F66: 0x25B6, 0x2F67: 0x25B8, 0x3062: 0x201C, 0x3063: 0x201D, 0x3066: 0x2027,
         0x3067: 0x2018, 0x3068: 0x2019, 0x309B: 0xFF62, 0x309D: 0xFF63, 0x2E01: 0x2460, 0x2E02: 0x2461, 0x2E03: 0x2462,
         0x2E04: 0x2463, 0x2E05: 0x2464, 0x2E06: 0x2465, 0x2E07: 0x2466, 0x2C21: 0x24D0, 0x2C22: 0x24D1, 0x2C23: 0x24D2,
         0x2C24: 0x24D3, 0x2C25: 0x24D4, 0x2C26: 0x24D5, 0x2C40: 0x3260, 0x2C41: 0x3261, 0x2C42: 0x3262,
         0x37C0: 0xD55C, 0x37C1: 0xAE00, 0x37C2: 0xACFC, 0x37C3: 0xCEF4, 0x37C4: 0xD4E8, 0x37C5: 0xD130}
BOX = "□"
_LINE = "\u250c\u252c\u2510\u251c\u253c\u2524\u2514\u2534\u2518\u2500\u2502"   # 선 그리기 문자 11방향(굵기 7종은 같은 모양으로)
# 한글 2024 가 3.0 문서를 5.x 로 올릴 때 KS 표와 다르게 옮기는 글자(공개 표본의 한글 저장본과 대조해 확인)
KS_FIX = {0x340D: 0xFF5E, 0x3481: 0x25C9}
_cache: dict[int, str] = {}


_NOTE_SUFFIX = re.compile("^(\\s*\u2063?\\d+\u2063?)\\)")   # 각주 첫머리 「번호)」


class Hwp3Error(Exception):
    pass


def _ks(code: int) -> str:
    """KS C 5601(완성형) 두 바이트 → 글자. 없는 자리면 빈 네모."""
    try:
        return bytes([code >> 8, code & 0xFF]).decode("euc_kr")
    except (UnicodeDecodeError, ValueError):
        return BOX


def _hangul(ch: int) -> str:
    """한글 3.0 조합형 16비트(초성 5·중성 5·종성 5) → 유니코드."""
    if ch == 0xD3C5:
        return "한"
    cho, jung, jong = (ch >> 10) & 0x1F, (ch >> 5) & 0x1F, ch & 0x1F
    if jung < 2:
        if jung == 0 and ch < 0xA414:
            i = cho * 32 + jong
            return chr(JAMO[i]) if i < len(JAMO) and JAMO[i] else BOX
        i = cho * 32 + jong - 308
        if 0 <= i < len(JAMOCOMP):
            return "".join(chr(v) for v in JAMOCOMP[i] if v) or BOX
        return BOX
    if cho == 1 and jong == 1:         # 모음만 — 요즘 모음이면 호환 자모(ㅏ…)로
        v = JUNG[jung]
        return chr(0x314F + v - 0x1161) if 0x1161 <= v <= 0x1175 else (chr(v) if v else BOX)
    if jung == 2 and jong == 1:        # 자음만 — 요즘 자음이면 호환 자모(ㄱ…)로
        v = CHO[cho]
        return _COMPAT_CHO[v - 0x1100] if 0x1100 <= v <= 0x1112 else (chr(v) if v else BOX)
    if (cho > 20 or cho == 0 or jung in (17, 24, 25) or jung > 29 or jong in (0, 18) or jong > 29 or cho == 1 or jung == 2):
        out = []
        if cho != 1 and CHO[cho]:
            out.append(chr(CHO[cho]))
        if jung > 2 and JUNG[jung]:
            out.append(chr(JUNG[jung]))
        if jong != 1 and JONG[jong]:
            out.append(chr(JONG[jong]))
        return "".join(out)
    c = cho - 2
    v = jung - (3 if jung < 8 else 5 if jung < 16 else 7 if jung < 24 else 9)
    t = jong - (2 if jong > 0x12 else 1)
    return chr(0xAC00 + c * 588 + v * 28 + t)


def _special(ch: int) -> str:
    """한글 3.0 특수 문자 영역(0x3400~) → KS 완성형 기호 → 유니코드."""
    if ch in (0x81, 0x82):
        return '"'
    if ch in (0x83, 0x84):
        return "'"
    idx = ch >> 8
    if idx == 0x1F:
        i = ch & 0xFF
        row = 170
        if i >= 0x60:
            row, i = 171, i - 0x60
        return _ks((row << 8) | (i + 160))
    if idx < 0x34 or idx >= 0x38:
        return BOX
    if ch >= 0x37C0:
        k = TG_KS[ch - 0x37C0] if ch - 0x37C0 < len(TG_KS) else 0
        return _ks(k) if k else BOX
    h = ch - 0x3400
    row, i = h // 0x60 + 161, h % 0x60 + 160
    if row == 170:
        row += 2
    return _ks((row << 8) | i)


# 한글 저장본과 맞대어 확인한 글자 부호 → 한컴 사용자 영역 코드.
# 선 그리기 0x3013~0x301D 는 본 7자(0x3013·14·15·19·1B·1C·1D)가 모두 0xF0806 부터 차례대로여서 그 사이 4자도 같은 규칙으로 둔다.
HANGUL_SEEN = {0x3013 + i: 0xF0806 + i for i in range(11)}
HANGUL_SEEN.update({0x2E00: 0xF0288, 0x2E0A: 0xF0289, 0x2E0B: 0xF028A, 0x2E0D: 0xF028C, 0x2E0E: 0xF028D, 0x2E0F: 0xF028E,
                    0x2E10: 0xF028F, 0x2E11: 0xF0290, 0x2E12: 0xF0291, 0x3366: 0xF03C5, 0x30BB: 0xF0854, 0x30BD: 0xF0855})


_HANGUL_TABLE: list | None | bool = False


def _hangul_table():
    """한글 2024 가 글자 부호 0x0080~0xFFFF 를 실제로 읽는 값(65,408개).

    부호마다 한 글자씩 담은 HWP 3.0 문서를 한글 2024 로 열어 HWPX 로 저장하고, 그 저장본에서 뽑았다(2026-11-28).
    한글이 저장한 실제 문서 12쌍에서 따로 본 1,234개 부호와 모두 같다. 표 파일이 없으면 아래의 규칙으로 읽는다."""
    global _HANGUL_TABLE
    if _HANGUL_TABLE is False:
        try:
            import zlib
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hwp3_hangul_map.bin"), "rb") as f:
                items = zlib.decompress(f.read()).decode("utf-8").split("\x00")
            _HANGUL_TABLE = items if len(items) == 0x10000 - 0x80 else None
        except Exception:
            _HANGUL_TABLE = None
    return _HANGUL_TABLE


def hchar(ch: int) -> str:
    """한글 3.0 글자 부호 하나 → 유니코드 문자열(옛한글은 여러 글자일 수 있다)."""
    if ch < 128:
        return chr(ch)
    s = _cache.get(ch)
    if s is not None:
        return s
    table = _hangul_table()
    if table is not None:
        s = table[ch - 0x80]
        _cache[ch] = s
        return s
    if 0xA0 <= ch <= 0xFF:
        s = chr(ch)
    elif ch == 0x8441:
        s = ""                     # 조합형의 빈 글자(초성·중성·종성 모두 채움) — 찍히는 것이 없다
    elif 0x37C0 <= ch <= 0x37C5:
        # 회사 이름 로고 여섯 글자. 한글이 5.x 로 올릴 때 쓰는 한컴 사용자 영역 코드와 같게 둔다(엔진도 같은 코드).
        s = chr(0xF03EF + ch - 0x37C0)
    elif ch == 0x37C6:
        # 제품 이름 로고의 첫 글자(아래아 「ᄒᆞᆫ」). 2.x 견본 25건에서 늘 「글」 앞, 제품 이름 자리에 온다.
        s = "\u1112\u119e\u11ab"
    elif 0x3590 <= ch <= 0x3599:
        s = chr(0x2160 + ch - 0x3590)
    elif 0x36E7 <= ch <= 0x36F0:
        s = chr(0x2460 + ch - 0x36E7)
    elif ch in HANGUL_SEEN:
        # 한글이 같은 문서를 5.x·HWPX 로 저장할 때 쓰는 한컴 사용자 영역 코드(저장본 12쌍에서 직접 본 것).
        s = chr(HANGUL_SEEN[ch])
    elif ch in EXTRA:
        s = chr(EXTRA[ch])
    elif ch & 0x8000:
        s = _hangul(ch)
    elif ch & 0x4000:
        i = ch - 0x4000
        s = _ks(((i // 94 + 0xCA) << 8) | (i % 94 + 0xA1)) if i < 4888 else BOX
    elif ch in KS_FIX:
        s = chr(KS_FIX[ch])
    elif 0x3013 <= ch < 0x3013 + 77:
        s = _LINE[(ch - 0x3013) % 11]
    elif 0x2100 <= ch <= 0x2BFF:      # 이 구간은 유니코드 값을 그대로 쓴다(화살표·수학 기호 등)
        s = chr(ch)
    elif 0x2F00 <= ch <= 0x2F6F and (ch & 0x0F) < 9:
        base = (0xA1E0 if ch < 0x2F10 else 0xA1DB if ch < 0x2F20 else 0xA1DE if ch < 0x2F30 else 0xA1E2 if ch < 0x2F40
                else 0xA1E4 if ch < 0x2F50 else 0xA2B7 if ch < 0x2F60 else 0xA2B9)
        s = _ks(base if (ch & 0x0F) < 6 else base + 1)
    else:
        s = _special(ch)
    _cache[ch] = s
    return s


# ---- 날짜 코드(특수 문자 8)·메일 머지(22): 한글 2024 가 올리는 꼴
#   한글은 날짜 코드를 DATE 필드로 올리고, 열 때마다 「오늘」 날짜로 다시 쓴다(탐침 문서 28가지 형식으로 확인).
#   형식 부호 → 한글 DateFormat: 1 YYYY · 2 M · 3 D · 02 MM · 03 DD · 4 h · 04 hh · 5 m · 05 mm · 6 E(요일) ·
#   ~6 G(한자 요일) · 7 a(오전/오후) · ~7 a(上午/下午) · $ h · % m · & c(a.m.) · + A(A.M.) · * MMMMMMMMM(달 이름) ·
#   @ MMM(달 약자.) · # F(서수 날짜) · ! YY. 그 밖의 글자는 그대로.
_DATE_TOK = {"1": "YYYY", "2": "M", "3": "D", "4": "h", "5": "m", "6": "E", "7": "a", "$": "h", "%": "m",
             "&": "c", "+": "A", "*": "MMMMMMMMM", "@": "MMM", "#": "F", "!": "YY"}
_DATE_PAD = {"2": "MM", "3": "DD", "4": "hh", "5": "mm"}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def _date_parts(fmt: str):
    """형식 부호 문자열을 (부호, 앞 0 여부, 한자 여부) 조각과 글자 조각으로 나눈다."""
    out, i = [], 0
    while i < len(fmt):
        c = fmt[i]
        if c == "0" and i + 1 < len(fmt) and fmt[i + 1] in _DATE_TOK:
            out.append(("tok", fmt[i + 1], True, False)); i += 2; continue
        if c == "~" and i + 1 < len(fmt) and fmt[i + 1] in "67":
            out.append(("tok", fmt[i + 1], False, True)); i += 2; continue
        if c in _DATE_TOK:
            out.append(("tok", c, False, False)); i += 1; continue
        out.append(("lit", c, False, False)); i += 1
    return out


def date_format_hangul(fmt: str) -> str:
    """원본 형식 부호 → 한글 DateFormat 문자열."""
    out = []
    for kind, c, pad, hanja in _date_parts(fmt):
        if kind == "lit":
            out.append(c)
        elif hanja:
            out.append("G" if c == "6" else "a")
        elif pad:
            out.append(_DATE_PAD.get(c, "0" + _DATE_TOK[c]))
        else:
            out.append(_DATE_TOK[c])
    return "".join(out)


def date_text(fmt: str, now=None) -> str:
    """원본 형식 부호로 날짜 글을 만든다(한글과 같이 지금 시각 기준)."""
    import datetime
    now = now or datetime.datetime.now()
    h12 = now.hour % 12 or 12
    am = now.hour < 12
    out = []
    for kind, c, pad, hanja in _date_parts(fmt):
        if kind == "lit":
            out.append(c); continue
        if hanja:
            out.append("日月火水木金土"[(now.weekday() + 1) % 7] if c == "6" else ("上午" if am else "下午")); continue
        if c == "1":
            v = str(now.year)
        elif c == "!":
            v = "%02d" % (now.year % 100)
        elif c in "23":
            n = now.month if c == "2" else now.day
            v = ("%02d" % n) if pad else str(n)
        elif c in "4$":
            v = ("%02d" % h12) if pad else str(h12)
        elif c in "5%":
            v = ("%02d" % now.minute) if pad else str(now.minute)
        elif c == "6":
            v = "일월화수목금토"[(now.weekday() + 1) % 7]
        elif c == "7":
            v = "오전" if am else "오후"
        elif c == "&":
            v = "a.m." if am else "p.m."
        elif c == "+":
            v = "A.M." if am else "P.M."
        elif c == "*":
            v = _MONTHS[now.month - 1]
        elif c == "@":
            v = _MONTHS[now.month - 1][:3] + "."
        elif c == "#":
            d = now.day
            v = str(d) + ("th" if 10 <= d % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th"))
        else:
            v = ""
        out.append(v)
    return "".join(out)


def _hchars(raw: bytes) -> str:
    out = []
    for (c,) in struct.iter_unpack("<H", raw[:len(raw) // 2 * 2]):
        if c == 0:
            break
        out.append(chr(c) if c < 0x80 else hchar(c))
    return "".join(out)


def merge_name(raw: bytes) -> str:
    """메일 머지 이름: 바이트 문자열(kchar, NUL 로 끝남). 한글은 첫 NUL 까지를 이름으로 쓴다."""
    b = raw.split(b"\0", 1)[0]
    try:
        return b.decode("cp949")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def hstr(raw: bytes) -> str:
    out = []
    for (c,) in struct.iter_unpack("<H", raw[:len(raw) // 2 * 2]):
        if c == 0:
            break
        out.append(hchar(c))
    return "".join(out)


class _R:
    __slots__ = ("b", "p")

    def __init__(self, b: bytes, p: int = 0):
        self.b, self.p = b, p

    def need(self, n: int):
        if n < 0 or self.p + n > len(self.b):
            raise Hwp3Error("자료가 끝나기 전에 문서가 끊겼습니다")

    def u8(self) -> int:
        self.need(1); v = self.b[self.p]; self.p += 1; return v

    def u16(self) -> int:
        self.need(2); v = self.b[self.p] | (self.b[self.p + 1] << 8); self.p += 2; return v

    def u32(self) -> int:
        self.need(4); v = int.from_bytes(self.b[self.p:self.p + 4], "little"); self.p += 4; return v

    def take(self, n: int) -> bytes:
        self.need(n); v = self.b[self.p:self.p + n]; self.p += n; return v

    def skip(self, n: int):
        self.need(n); self.p += n


def is_hwp3(path: str) -> bool:
    """HWP 3.0·2.1·2.0·1.x(서명 「HWP Document File V…」로 시작하고 OLE 가 아닌 옛 형식)인가."""
    try:
        with open(path, "rb") as f:
            head = f.read(23)
            return head in SIGNATURES or head.startswith(V1_PREFIX)
    except OSError:
        return False


def _plain(blocks) -> str:
    return " ".join(b.text for b in blocks if isinstance(b, Paragraph)).strip()


def _has_text(blocks) -> bool:
    for b in blocks:
        if isinstance(b, Paragraph):
            if b.text.strip():
                return True
        elif isinstance(b, Table):
            if any(_has_text(c.blocks) for c in b.cells):
                return True
        elif isinstance(b, (TextBox, Note, HeaderFooter)):
            if _has_text(b.blocks):
                return True
        else:
            return True
    return False


class _Parser:
    def __init__(self, r: _R, st: dict):
        self.r, self.st, self.depth = r, st, 0

    # ---- 문단 목록: 글자 수 0 인 문단이 끝 표지
    def para_list(self) -> list:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise Hwp3Error("문단이 너무 깊게 겹쳐 있습니다")
        out: list = []
        top = self.depth == 1 and self.st.get("salvage")
        try:
            while True:
                mark = self.r.p
                try:
                    more, blocks = self.para()
                except (Hwp3Error, struct.error, IndexError) as e:
                    if not top:
                        raise
                    # 문서가 중간에 끊겼거나 깨졌다: 마지막으로 온전히 읽힌 문단까지만 쓴다
                    self.st["cut"], self.st["cut_error"], self.st["cut_paras"] = mark, str(e), len(out)
                    break
                if not more:
                    break
                out.extend(blocks)
        finally:
            self.depth -= 1
        return out

    def para(self):
        r = self.r
        hdr = r.p
        reuse = r.u8()
        nch = r.u16()
        nline = r.u16()
        contain = r.u8()
        r.skip(1 + 4 + 1)          # 기타 플래그, 특수 문자 플래그, 스타일 번호
        cs = self.st.get("cshape", CSHAPE)
        v20 = self.st.get("ver") == 200
        flagpos: list = []         # 글자별 모양 표지의 자리(2.0 → 3.0 올림에서 개요 번호 자리를 늘릴 때 쓴다)
        outline_at: list = []
        ed = self.st.get("edits") if cs != CSHAPE else None   # 2.0 → 3.0 올림: 글자 모양 25 → 31 바이트
        p0 = r.p
        raw = r.take(cs)           # 대표 글자 모양
        if ed is not None:
            ed.append((p0, cs, _cshape_v20(raw)))
        if nch and not reuse:
            ps_at = r.p
            self.st["pshape_last"] = (ps_at, r.take(PSHAPE))
            if self.st.get("pshape_edit") is not None:
                self.st["pshape_edit"].append(ps_at)
        if nch and self.st.get("pshapes") is not None:     # 진단용: 문단별 문단 모양(재사용이면 앞 문단 것)
            self.st["pshapes"].append((self.st.get("pshape_last") or (0, b""))[1])
        r.skip(LINEINFO * nline)
        if not nch:
            return False, []
        if contain:
            for _ in range(nch):
                flagpos.append(r.p)
                if not r.u8():
                    p0 = r.p
                    raw = r.take(cs)
                    if ed is not None:
                        ed.append((p0, cs, _cshape_v20(raw)))
            flagpos.append(r.p)
        out: list = []
        buf: list[str] = []
        trailing: list = []

        def flush():
            t = "".join(buf).strip("\n")
            buf.clear()
            if t.strip():
                out.append(Paragraph(t.strip() if "\n" not in t else t))

        i = 0
        while i < nch:
            hh = r.u16()
            if hh == 13:
                break
            if hh >= 32:
                buf.append(hchar(hh))
                i += 1
                continue
            if hh == 28 and v20:    # 2.0 의 개요 번호는 22 바이트(11 글자 자리). 3.0 은 64 바이트(32 자리)
                outline_at.append(i)
                i += 11
            else:
                i += WSIZE[hh]
            inline, blocks, splits = self.special(hh)
            if inline:
                buf.append(inline)
            if splits:
                flush()
                out.extend(blocks)
            elif blocks:
                trailing.extend(blocks)
        flush()
        out.extend(trailing)
        if outline_at and ed is not None:
            # 3.0 꼴로 늘어난 21 글자 자리만큼 문단의 글자 수와 글자별 모양 표지(앞 글자와 같음 = 1)를 늘린다
            ed.append((hdr + 1, 2, struct.pack("<H", nch + 21 * len(outline_at))))
            if contain:
                for k in outline_at:
                    ed.append((flagpos[min(k + 11, nch)], 0, b"\x01" * 21))
        return True, out

    def _dummy(self, hh: int):
        if self.r.u16() != hh:
            raise Hwp3Error(f"특수 문자 {hh} 의 짝이 맞지 않습니다")

    def special(self, hh: int):
        r = self.r
        if hh in SKIP_BLOCK:
            n = r.u32(); self._dummy(hh); r.skip(n)
            return "", [], False
        if hh == 5:                # 필드 코드(누름틀·계산식 등)
            r.skip(4); r.skip(2); r.skip(2 + 4 + 2 + 22)
            l1, l2, l3, lb = r.u32(), r.u32(), r.u32(), r.u32()
            r.skip(l1 + l2 + l3 + lb)
            return "", [], False
        if hh == 6:                # 책갈피
            r.skip(4); self._dummy(hh); r.skip(32 + 2)
            return "", [], False
        if hh == 7:                # 날짜 형식
            r.skip(80); self._dummy(hh)
            return "", [], False
        if hh == 8:                # 날짜 코드 — 한글은 오늘 날짜로 다시 쓴다(변환본 뒤처리도 같게 채운다)
            raw8 = r.take(80 + 12); self._dummy(hh)
            if self.st.get("dates_raw") is not None:    # 진단용
                self.st["dates_raw"].append(raw8)
            return date_text(_hchars(raw8[:80])), [], False
        if hh == 9:                # 탭
            r.skip(4); self._dummy(hh)
            return "\t", [], False
        if hh == 10:
            return self.box()
        if hh == 11:
            return self.picture()
        if hh == 14:               # 선
            r.skip(4); self._dummy(hh)
            rawl = r.take(8 + 2 + 8 + 24 + 14 + 4 + 2 + 8 + 14)
            if self.st.get("lines_raw") is not None:    # 진단용
                self.st["lines_raw"].append(rawl)
            return "", [], True    # 선도 개체다 — 다른 판독기(5.x·HWPX)와 같이 그 자리에서 글을 끊는다
        if hh == 15:               # 숨은 설명 — 화면에 보이지 않는 글(5.x 판독기와 같이 글로 내지 않는다)
            r.skip(4); self._dummy(hh); r.skip(8)
            self.para_list()
            return "", [], False
        if hh == 16:               # 머리말·꼬리말
            r.skip(4); self._dummy(hh); r.skip(8)
            kind = r.u8(); r.skip(1)
            return "", [HeaderFooter("header" if kind == 0 else "footer", self.para_list())], False
        if hh == 17:               # 각주·미주
            r.skip(4); self._dummy(hh); r.skip(8)
            r.skip(2); kind = r.u16(); r.skip(2)
            end = kind != 0
            key = "en_no" if end else "fn_no"
            self.st[key] += 1
            no = self.st[key]
            blocks = self.para_list()
            if self.st.get("fn_bracket") and blocks and isinstance(blocks[0], Paragraph):
                # 「1) …」의 닫는 괄호는 3.0 이 번호 뒤에 글자로 넣어 둔 번호 장식이다. 5.x·HWPX 에서는 각주 모양의
                # 뒤 장식 속성으로 옮겨지고 글에서는 빠지므로, 원본 판독에서도 글로 세지 않는다
                blocks[0].text = _NOTE_SUFFIX.sub(r"\1", blocks[0].text, count=1)
                if not blocks[0].text.strip():
                    blocks.pop(0)
            return (f"[^미{no}]" if end else f"[^{no}]"), [Note("endnote" if end else "footnote", no, blocks)], False
        if hh == 18:               # 자동 번호: 0 쪽, 1 각주, 2 미주, 3 그림, 4 표, 5 수식
            kind, num = r.u16(), r.u16(); self._dummy(hh)
            if kind == 0:
                return "", [], False
            n = str(num)
            return (AUTONUM_MARK + n + AUTONUM_MARK if self.st.get("autonum_mark") else n), [], False
        if hh in (19, 20, 21):     # 새 번호, 쪽 번호 달기, 홀수 쪽·감추기
            r.skip(4); self._dummy(hh)
            return "", [], False
        if hh == 22:               # 메일 머지 — 한글은 {{이름}} 글이 든 MAILMERGE 필드로 올린다
            raw22 = r.take(20); self._dummy(hh)
            if self.st.get("merges_raw") is not None:   # 진단용
                self.st["merges_raw"].append(raw22)
            return "{{" + merge_name(raw22) + "}}", [], False
        if hh == 23:               # 글자 겹침
            r.skip(6); self._dummy(hh)
            # 겹쳐 찍는 글자(㉠·○인 같은 모양)는 변환본에서 글자 겹침 개체(compose)로 간다. 5.x·HWPX 판독기가
            # 이 개체 안 글자를 본문 글로 내지 않으므로 여기서도 내지 않는다(대조 범위를 맞춤).
            return "", [], False
        if hh == 24:               # 하이픈
            r.skip(2); self._dummy(hh)
            return "", [], False
        if hh == 25:               # 제목·표·그림 차례 표시
            r.skip(2); self._dummy(hh)
            return "", [], False
        if hh == 26:               # 찾아보기 표시
            r.skip(120 + 120 + 2); self._dummy(hh)
            return "", [], False
        if hh == 28:               # 개요 번호
            if self.st.get("ver") == 200:      # 2.0: 종류 2 + 모양 1 + 수준 1 + 번호 14 뿐(사용자 모양·장식 없음)
                r.skip(2 + 1 + 1 + 14)
                ed = self.st.get("edits")
                if ed is not None:
                    ed.append((r.p, 0, b"\0" * 42))
                self._dummy(hh)
                return "", [], False
            r.skip(2 + 1 + 1 + 14 + 14 + 28); self._dummy(hh)
            return "", [], False
        if hh in (30, 31):         # 묶음 빈칸, 고정 폭 빈칸
            self._dummy(hh)
            return " ", [], False
        raise Hwp3Error(f"알 수 없는 특수 문자 {hh}")

    # ---- 표·글상자·수식·버튼 (10)
    def box(self):
        r = self.r
        r.skip(4); self._dummy(10)
        box0 = r.p
        r.skip(8)                                  # 길이·다음 정보
        r.skip(1 + 1 + 2 + 2)                      # 기준 위치, 배치, 가로·세로 위치
        option = r.u16()                           # 기타 옵션 — 0x10 = 하이퍼텍스트 상자
        r.skip(2 + 24)                             # 제어 문자, 여백
        r.skip(2 * 8 + 4 + 2 * 6)                  # 크기들, 위치 종류, 쪽 좌표, 캡션 위치, 번호
        r.skip(2 + 2)                              # 예약, 기준선
        kind = r.u16()
        ncell = r.u16()
        r.skip(2)
        if ncell <= 0 or ncell > 65535:
            raise Hwp3Error("표의 칸 수가 올바르지 않습니다")
        geo = []
        for _ in range(ncell):
            rawc = r.take(CELL)
            x, y, w, h = struct.unpack_from("<4H", rawc, 4)
            geo.append((x, y, w, h))
            if self.st.get("cells_raw") is not None:    # 진단용
                self.st["cells_raw"].append((kind, rawc))
        if self.st.get("boxes_raw") is not None:        # 진단용: 상자 정보 84 바이트와 칸 정보
            self.st["boxes_raw"].append((kind, bytes(r.b[box0:box0 + 84]), bytes(r.b[box0 + 84:r.p])))
        lists = [self.para_list() for _ in range(ncell)]
        caption = self.para_list()
        cap = _plain(caption)
        if option & 0x10 and not any(_has_text(b) for b in lists):
            # 글이 없는 하이퍼텍스트 상자는 화면에 아무것도 그려지지 않는 연결 자리다(한글 2024 도 표로 올리지 않는다)
            return "", ([Paragraph(cap)] if cap else []), False
        if kind == 0:
            # 글이 없는 실금 칸(너비나 높이 50 단위 이하)은 한글이 칸으로 올리지 않는다 — 경계선만 남기고 뺀다
            keep = [not ((g[2] <= 50 or g[3] <= 50) and not _has_text(b)) for g, b in zip(geo, lists)]
            if not any(keep):
                keep = [True] * len(geo)
            nr, nc, addr = _grid(geo, keep)
            self.st["table_no"] += 1
            t = Table(nr, nc, id=self.st["table_no"], caption=cap)
            cells = [Cell(a[0], a[1], a[2], a[3], blocks) for a, blocks, k in zip(addr, lists, keep) if k]
            covered = {(c.row + i, c.col + j) for c in cells for i in range(c.rowspan) for j in range(c.colspan)}
            if len(covered) < nr * nc <= 20000:         # 어느 칸도 덮지 않는 자리는 빈 칸으로 채운다(한글도 그렇게 올린다)
                cells.extend(Cell(i, j, 1, 1, []) for i in range(nr) for j in range(nc) if (i, j) not in covered)
            cells.sort(key=lambda c: (c.row, c.col))
            t.cells = cells
            return "", [t], True
        body = [b for blocks in lists for b in blocks]
        if kind == 2:
            return "", [Equation(_plain(body), caption=cap)], True
        # 글상자·버튼: 3.0 의 글상자는 칸 하나짜리 틀이다. 한글 2024 가 5.x 로 올릴 때 1행 1열 표로 바꾸므로 같은 모양으로 올린다
        self.st["table_no"] += 1
        t = Table(1, 1, id=self.st["table_no"], caption=cap)
        t.cells = [Cell(0, 0, 1, 1, body)]
        return "", [t], True

    # ---- 2.x 의 그림: 2.1 은 164 바이트, 2.0 은 132 바이트. 길이 정보·그림 종류·확대 비율이 없고 파일 이름이 80 바이트다.
    #      (2.0 13건·2.1 315건 표본을 파일 끝까지 읽어 확인. 그림은 모두 바깥 파일 연결이다)
    def _picture_v2(self):
        r = self.r
        p0 = r.p - 2
        r.skip(4); self._dummy(11)
        r.skip(8)                                  # 실행 중 주소 값(뜻 없음)
        head = r.take(48)                          # 기준 위치 … 전체 크기(3.0 과 같은 순서)
        tail16 = r.take(16)                        # 쪽 좌표 등(3.0 과 배치가 다름 — 엔진이 다시 계산한다)
        if self.st.get("pics_raw") is not None:    # 진단용
            self.st["pics_raw"].append((head, tail16))
        num = r.take(2)                            # 상자 번호
        plen = 48 if self.st.get("ver") == 200 else 80      # 2.0 은 파일 이름 칸이 48 바이트(표본 1건으로 확인)
        path = r.take(plen)
        r.skip(2)
        if plen == 80:
            # 2.1 의 파일 이름 칸 42~45 바이트 = 그림 자르기 왼쪽·위(hunit). 한글 2024 는 그림 크기에서 이만큼 빼고
            # imgClip 왼쪽·위에 ×4 로 적는다(정답지 v21_05: 248·142 → 크기 −992·−568, imgClip 992·568).
            # 46~49 바이트(206·85)는 한글이 크기에 쓰지 않았다 — 뜻 미확인이라 옮기지 않는다.
            cl, ct = struct.unpack_from("<HH", path, 42)
            if (cl or ct) and path[:42].count(b"\0"):
                h = bytearray(head)
                for off, d in ((34, cl), (36, ct), (44, cl), (46, ct)):
                    v = struct.unpack_from("<H", h, off)[0]
                    struct.pack_into("<H", h, off, max(v - d, 0))
                head = bytes(h)
        ed = self.st.get("edits")
        if ed is not None:
            new = (b"\x0b\0" + b"\0" * 4 + b"\x0b\0" + b"\0" * 8 + head + b"\0" * 2 + b"\0" * 4 + b"\0" * 6
                   + b"\x01\0" + b"\0" * 2 + num + b"\0" + b"\0" * 8 + path.split(b"\0", 1)[0].ljust(256, b"\0") + b"\0" * 9)
            ed.append((p0, 84 + plen, new))
        cap = _plain(self.para_list())
        name = path.split(b"\0", 1)[0].decode("cp949", "replace").replace("\\", "/").rsplit("/", 1)[-1]
        return "", [Image(name, caption=cap)], True

    # ---- 그림 (11): 0 외부 파일, 1 OLE, 2 내장 그림, 3 그리기 개체
    def picture(self):
        r = self.r
        if self.st.get("ver", 300) < 300:
            return self._picture_v2()
        r.skip(4); self._dummy(11)
        follow = r.u32()
        r.skip(4)
        r.skip(1 + 1 + 2 + 2 + 2 + 2 + 24)
        r.skip(2 * 8 + 4 + 2 * 6)
        ptype = r.u8()
        r.skip(8)
        path = r.take(256)
        r.skip(9)
        extra = r.take(follow) if follow else b""
        cap = _plain(self.para_list())
        out: list = []
        if ptype == 3:
            out.extend(_drawing_blocks(extra, self))
        else:
            raw = path.split(b"\0", 1)[0]
            name = raw.decode("cp949", "replace")
            if ptype == 2:
                name = "HWP" + name[3:] if len(name) >= 3 else name
            else:
                name = name.replace("\\", "/").rsplit("/", 1)[-1]
            out.append(Image(name, caption=cap))
            cap = ""
        if cap:
            out.append(Paragraph(cap))
        return "", out, True


def _grid(geo: list, keep: list | None = None) -> tuple:
    """표 칸 좌표(x, y, 너비, 높이) → (행 수, 열 수, 칸마다 (행, 열, 행병합, 열병합)).
    3.0 은 칸 주소 대신 좌표만 저장한다. 줄·칸 경계는 「칸이 시작하는 자리」로 잡는다. 병합 수는 같은 줄에서
    바로 오른쪽(아래)에 붙은 칸의 시작 자리까지로 센다 — 칸 끝 좌표는 이웃 칸 시작과 1~2 단위씩 어긋나
    있어 그대로 쓰면 병합 수가 틀린다. 한글 2024 저장본 표 113개와 대조해 맞춘 규칙이다."""
    def axis(a: int, b: int):
        lines = sorted({g[a] for g in geo})
        idx = {v: i for i, v in enumerate(lines)}
        out = []
        simple = len(geo) > 1500
        live = [h for h, k in zip(geo, keep or [True] * len(geo)) if k]
        for g in geo:
            s_, e = g[a], g[a] + g[a + 2]
            nxt = None
            if not simple:
                lo, hi = g[b], g[b] + g[b + 2]
                mid = s_ + g[a + 2] / 2
                for h in live:
                    if h[a] > mid and h[b] < hi and h[b] + h[b + 2] > lo and (nxt is None or h[a] < nxt):
                        nxt = h[a]
            if nxt is not None:
                span = idx[nxt] - idx[s_]
            else:                       # 오른쪽(아래)에 붙은 칸이 없다 — 자기 끝 좌표로 센다
                span = sum(1 for v in lines[idx[s_]:] if v < e)
            out.append((idx[s_], max(span, 1)))
        return len(lines), out
    nc, xs = axis(0, 1)
    nr, ys = axis(1, 0)
    return max(nr, 1), max(nc, 1), [(y[0], x[0], y[1], x[1]) for x, y in zip(xs, ys)]


def _drawing_blocks(data: bytes, parser: "_Parser") -> list:
    """그리기 개체 묶음(선·사각형·타원·자유선·글상자·묶음) — 글상자와 「글상자로 쓰는 도형」 속 글을 꺼낸다."""
    st = parser.st
    st["drawings"] = st.get("drawings", 0) + 1
    out: list = []
    r = _R(data)
    sub = _Parser(r, st)
    sub.depth = parser.depth

    def paras() -> list:
        blocks = sub.para_list()
        return [TextBox(blocks)] if blocks else []

    def objects(level: int):
        if level > MAX_DEPTH:
            raise Hwp3Error("그리기 개체가 너무 깊게 겹쳐 있습니다")
        while True:
            size = r.u32()
            start = r.p
            if size < 88:
                raise Hwp3Error("그리기 개체 머리가 올바르지 않습니다")
            kind, link = r.u16(), r.u16()
            r.skip(24 + 16 + 40)
            flag = r.u32()
            used = 88
            for bit, n in ((0x20000, 32), (0x10000, 28), (0x40000, 278)):
                if flag & bit and size >= used + n:
                    r.skip(n); used += n
            if flag & 0x100000 and size >= used + 3:
                n = 5 if size - used >= 5 else 3
                r.skip(n); used += 5
            if flag & 0x80000 and size > used:          # 도형을 글상자로 씀
                r.skip(8)
                out.extend(paras())
            else:
                r.p = start + size
            n1 = r.u32(); r.skip(n1)                    # 개체별 정보 1
            n2 = r.u32()                                # 개체별 정보 2 (글상자는 문단 목록)
            if kind == 6:
                out.extend(paras())
            else:
                r.skip(n2)
            if link & 2:
                objects(level + 1)
            if not link & 1:
                return

    try:
        size = r.u32()
        if size < 24:
            return out
        r.skip(size)
        objects(0)
    except Hwp3Error:
        st.setdefault("notes", []).append("그리기 개체 일부를 읽지 못했습니다")
    return out


def _cshape_v20(raw: bytes) -> bytes:
    """2.0 의 글자 모양(언어 5종, 25 바이트)을 3.0 꼴(7종, 31 바이트)로.
    2.0 의 다섯 언어는 한글·영문·한자·일어·기타다 — 한글 2024 자동 저장 정답지(언어마다 글꼴·장평·자간을
    다르게 준 탐침 문서)에서 다섯째가 「기타」로 올라가고 「기호」「사용자」는 첫 글꼴·장평 100·자간 0 이다."""
    def seven(a: bytes, fill: int) -> bytes:
        return a[:5] + bytes([fill, fill])
    return raw[:2] + seven(raw[2:7], 0) + seven(raw[7:12], 100) + seven(raw[12:17], 0) + raw[17:25]


def _open_old(data: bytes):
    """머리를 읽어 (판, 정보, 본문 바이트, 본문 시작 자리) 를 돌려준다. 판: 300·210·200."""
    from .hwp5 import EncryptedDocument
    sig = data[:23]
    if sig not in SIGNATURES:
        raise Hwp3Error("HWP 3.0·2.x 문서가 아닙니다")
    ver = {SIGNATURES[0]: 300, SIGNATURES[1]: 210, SIGNATURES[2]: 200}[sig]
    if len(data) < ID_LEN + INFO_LEN + SUMMARY_LEN:
        raise Hwp3Error("문서 머리가 잘렸습니다")
    info = data[ID_LEN:ID_LEN + INFO_LEN]
    if struct.unpack_from("<H", info, 96)[0]:
        raise EncryptedDocument("열기 암호가 걸린 문서입니다(한글에서 암호를 풀어 저장해야 판독 가능).", "")
    start = ID_LEN + INFO_LEN + SUMMARY_LEN + struct.unpack_from("<H", info, 126)[0]
    body = data[start:]
    if info[124]:
        body = _inflate_all(body)
    return ver, info, body, start


def _walk_old(ver: int, info: bytes, body: bytes, autonum_mark=False, visible=False, edits=None):
    """글꼴·스타일을 넘기고 문단 목록을 읽는다. (블록들, 읽기 자리, 상태) 를 돌려준다."""
    nlang, cs = (5, 25) if ver == 200 else (7, CSHAPE)
    r = _R(body)
    fonts = []
    for _ in range(nlang):                             # 언어별 글꼴 이름
        p0 = r.p
        n = r.u16()
        if n > 4096:
            raise Hwp3Error("글꼴 목록이 올바르지 않습니다")
        r.skip(n * 40)
        fonts.append(body[p0:r.p])
    if edits is not None and ver == 200:               # 3.0 은 7종: 한글·영문·한자·일어·기타·기호·사용자
        one = b"\x01\0" + (fonts[0][2:42] if len(fonts[0]) >= 42 else b"\0" * 40)
        edits.append((0, r.p, b"".join(fonts[:5]) + one + one))
    nsty = r.u16()
    if nsty > 4096:
        raise Hwp3Error("스타일 목록이 올바르지 않습니다")
    for _ in range(nsty):
        r.skip(20)
        p0 = r.p
        raw = r.take(cs)
        if edits is not None and ver == 200:
            edits.append((p0, cs, _cshape_v20(raw)))
        r.skip(PSHAPE)
    st = {"table_no": 0, "fn_no": 0, "en_no": 0, "autonum_mark": autonum_mark, "visible": visible,
          "fn_bracket": info[110], "ver": ver, "cshape": cs, "salvage": True}
    if edits is not None:
        st["edits"] = edits
    p = _Parser(r, st)
    blocks = p.para_list()
    return blocks, r, st, p


# ---- HWP 1.x (서명 V1.10 — 한글 1.2 견본 1건으로 확인한 구조)
#   서명 30 + 문서 정보 128 + 문단들. 문단 = 머리 20 바이트 + 글자(부호 2 + 글자 속성 2)들, 0x000D 로 끝난다.
#   표·그림 같은 개체가 없다. 부호 0 은 자리 채움(줄 나눔 자리)이라 글자가 아니다.
#   글자 속성(글꼴·크기·꾸밈)의 비트 뜻은 확인하지 못해 읽지 않는다.
def _v1_paras(data: bytes) -> list:
    """1.x 문단들의 글자 부호 목록. V1.10 은 글자마다 속성 2바이트가 붙고(글자 4바이트),
    V1.20 은 문단 머리 뒤에 속성 구간(길이 1 + 속성 2)들이 0 으로 끝나고 글자는 2바이트다
    (V1.20 은 한글 2024 저장본과 글이 같은 것을 확인)."""
    ver = data[19:23]
    if ver == b"1.10":
        return _v1_paras_110(data)
    if ver == b"1.20":
        return _v1_paras_120(data)
    raise Hwp3Error(f"HWP {ver.decode('ascii', 'replace')} 문서는 구조를 확인하지 못해 읽지 않습니다")


def _v1_paras_120(data: bytes) -> list:
    out, p, n = [], ID_LEN + INFO_LEN, len(data)
    while p + 20 <= n:
        p += 20
        count = 0
        while True:                                     # 속성 구간: (글자 수 1, 속성 2) … 0
            if p >= n:
                return out
            ln = data[p]
            p += 1
            if not ln:
                break
            p += 2
            count += ln
        if not count:
            break
        codes = []
        for _ in range(count):
            if p + 2 > n:
                if codes:
                    out.append(codes)
                return out
            c = struct.unpack_from("<H", data, p)[0]
            p += 2
            if c == 13:
                continue
            if c:
                codes.append(c if (32 <= c < 0x80 or c >= 0x8000) else 32)
        out.append(codes)
        if len(out) > 2_000_000:
            raise Hwp3Error("문단이 너무 많습니다")
    return out


def _v1_paras_110(data: bytes) -> list:
    out, p, n = [], ID_LEN + INFO_LEN, len(data)
    while p + 20 <= n:
        p += 20
        codes = []
        while True:
            if p + 4 > n:
                if codes:
                    out.append(codes)
                return out
            c = struct.unpack_from("<H", data, p)[0]
            p += 4
            if c == 13:
                break
            if c:
                codes.append(c if (32 <= c < 0x80 or c >= 0x8000) else 32)
        out.append(codes)
        if len(out) > 2_000_000:
            raise Hwp3Error("문단이 너무 많습니다")
    return out


_V3_INFO = bytes.fromhex("0000000003013752223a890589054e084e0800000000000000000000000001" + "00" * 67
                         + "010001000000d5008e0047002900" + "00" * 16)
_V3_CS = bytes.fromhex("fa000000000000000064646464646464" + "00" * 15)
_V3_PS = bytes.fromhex("0000000000007800000000060000000000" + "".join("%08x" % int.from_bytes((1000 * i).to_bytes(4, "little"), "big") for i in range(1, 32))
                       + "00" * 31 + "01" + "00" * 14)


# ---- HWP 1.20 → 3.0 올림 (글자·문단·쪽 모양 포함)
#   한글 2024 가 1.20 문서 13건을 연 결과(자동 저장 HWPX)와 원본 바이트를 맞대어 확인한 구조다.
#   문서 정보(128): [7] 위 [9] 아래 [11] 머리말 [13] 꼬리말 [15] 왼쪽 여백(mm, 왼쪽은 +6mm), [17:19] 용지 길이(0.1mm)
#   문단 머리(20): [0] 줄 수-1  [2] 정렬(3.0 과 같은 번호)  [3] 줄 간격 덧값  [5] 들여쓰기(칸, 부호 있음)
#                  [7] 왼쪽 여백(칸)  [9] 오른쪽 끝 칸
#   글자 속성(2): 첫 바이트 0x80 가로 2배 · 0x40 세로 2배 · 0x20 진하게 · 0x10 밑줄 · 0x08 역상 · 0x04 음영,
#                 둘째 바이트 아래 2비트 = 글꼴(명조·고딕·샘물·필기) · 0x04 기울임
#   한 칸 = 126.25 hunit(5pt × 자간 1%). 한글 2024 는 1.x 를 3.0 을 거쳐 올리므로 여기서 3.0 값으로 옮기면
#   변환 엔진의 3.0 규칙이 그대로 적용된다.
_V1_FONTS = ("명조", "고딕", "샘물", "필기")
_V1_COL = 126.25


def _v1_mm(mm: int) -> int:
    return int(mm * 1800 / 25.4 + 0.5)


def _v1_fontlist(names) -> bytes:
    return struct.pack("<H", len(names)) + b"".join(n.encode("johab").ljust(40, b"\0") for n in names)


def _v1_cshape(flag: int, fh: int, fl: int, italic: bool = False) -> bytes:
    size = 500 if flag & 0x40 else 250
    bold = bool(flag & 0x20)
    ratios = [102, 91, 102, 100, 100, 100, 100] if bold else [100] * 7
    if flag & 0x80:
        ratios = [r * 2 for r in ratios]
    if flag & 0x40:
        ratios = [r // 2 for r in ratios]
    ratios = [min(200, max(50, r)) for r in ratios]
    spacing = [-5, 1, -5, 1, 1, 1, 1] if bold else [1] * 7
    attr = (1 if italic else 0) | (2 if bold else 0) | (4 if flag & 0x10 else 0)
    shade_color, text_color, shade_ratio = 0, 0, 0
    if flag & 0x08:                                     # 역상: 검정 바탕에 흰 글자
        text_color, shade_ratio = 7, 100
    elif flag & 0x04:                                   # 음영 30%
        shade_ratio = 30
    return (struct.pack("<H", size) + bytes([fh, fl, 0, 0, 0, 0, 0]) + bytes(ratios) + bytes(x & 255 for x in spacing)
            + bytes([shade_color, text_color, shade_ratio, attr]) + b"\0" * 4)


def _v1_pshape(left=0, right=0, indent=0, ls=160, align=6) -> bytes:
    tabs = b"".join(struct.pack("<BBH", 0, 0, 1000 * i) for i in range(1, 41))
    return (struct.pack("<HHhHHBB", left, right, indent, ls, 0, 0, align) + tabs + struct.pack("<BBH", 1, 0, 0)
            + b"\0" * 4 + b"\0" * 3 + struct.pack("<H", 0) + b"\0\0")


def _v1_parse_120(data: bytes) -> list:
    """(문단 머리 20, [(글자 부호, 속성 2바이트)…]) 목록. 부호 0(자리 채움)·13 은 뺀다."""
    out, p, n = [], ID_LEN + INFO_LEN, len(data)
    while p + 20 <= n:
        hdr = data[p:p + 20]
        p += 20
        runs, count = [], 0
        while True:
            if p >= n:
                return out
            ln = data[p]
            p += 1
            if not ln:
                break
            if p + 2 > n:
                return out
            runs.append((ln, data[p:p + 2]))
            p += 2
            count += ln
        if not count:
            break
        chars, cells, stop = [], 0, False
        for ln, at in runs:
            for _ in range(ln):
                if p + 2 > n:
                    stop = True
                    break
                c = struct.unpack_from("<H", data, p)[0]
                p += 2
                if c in (0, 13):
                    continue
                cells += (2 if c >= 0x100 else 1) * (2 if at[0] & 0x80 else 1)
                # 1.x 의 특수 글자(0x80~0x7FFF: 선 그리기·기호)는 한글 2024 가 모두 빈칸으로 올린다
                # (정답지 13건의 75종 9,600여 자 전부). 맞는 글자를 확인할 길이 없어 같은 꼴로 둔다.
                chars.append((c if (32 <= c < 0x80 or c >= 0x8000) else 32, at))
            if stop:
                break
        out.append((hdr, chars, cells))
        if stop:
            return out
        if len(out) > 2_000_000:
            raise Hwp3Error("문단이 너무 많습니다")
    return out


def _upconvert_v1_120(data: bytes) -> bytes:
    info = data[ID_LEN:ID_LEN + INFO_LEN]
    paras = _v1_parse_120(data)
    ph = struct.unpack_from("<H", info, 17)[0]          # 용지 길이(0.1mm)
    pw = struct.unpack_from("<H", info, 19)[0]
    if abs(ph - 2970) <= 2:                             # A4 는 210×297mm 로 맞춘다(정답지 4건)
        page_w, page_h = 14882, 21047
    else:
        page_w, page_h = int(pw * 1800 / 254 + 0.5), int(ph * 1800 / 254 + 0.5)
    m_top, m_bottom, m_head, m_foot = (_v1_mm(info[i]) for i in (7, 9, 11, 13))
    m_left = _v1_mm(info[15] + 6)
    width = lambda last_col: int((last_col + 2) * _V1_COL)
    # 한 문단이라도 양쪽 여백 안에 들어가지 않으면 오른쪽 여백은 0 이다
    m_right = 0 if any(width(h[9]) > page_w - 2 * m_left for h, _c, _n in paras) else m_left
    text_w = page_w - m_left - m_right
    v3info = bytearray(_V3_INFO)
    v3info[5] = 0                                       # 용지 방향: 좁게
    struct.pack_into("<9H", v3info, 6, page_h, page_w, m_top, m_bottom, m_left, m_right, m_head, m_foot, 0)
    fonts = _v1_fontlist(_V1_FONTS) * 2 + _v1_fontlist(_V1_FONTS[:1]) * 5
    body = [fonts, struct.pack("<H", 1), "바탕글".encode("johab").ljust(20, b"\0"),
            _v1_cshape(0, 0, 0), _v1_pshape(ls=130)]
    fh = fl = 0                                         # 한글·영문 글꼴은 그 언어 글자가 나올 때만 바뀐다
    last_cs = _v1_cshape(0, 0, 0)
    for hdr, chars, cells in paras:
        shapes = []
        for c, at in chars:
            f = at[1] & 3
            if c >= 0x8000:
                fh = f
            elif c < 0x80 and c != 32:
                fl = f
            shapes.append(_v1_cshape(at[0], fh, fl, bool(at[1] & 0x04)))
        if shapes:
            last_cs = shapes[-1]
        shapes.append(last_cs)                          # 문단 끝(13)은 마지막 글자 모양을 따른다
        size = 500 if any(at[0] & 0x40 for _c, at in chars) else 250
        ls = 0x8000 | (size + 50 + 18 * hdr[3])
        w = width(hdr[9])
        if cells > hdr[9] + 1:                          # 한 줄을 넘는 문단은 폭이 106.25 만큼 좁다(정답지 1,100여 문단)
            w = int((hdr[9] + 2) * _V1_COL - 106.25)
        right = 0 if w >= text_w else text_w - w
        ind = int(struct.unpack("b", hdr[5:6])[0] * _V1_COL)
        left = int(hdr[7] * _V1_COL)
        ps = _v1_pshape(left=left, right=min(right, 65535), indent=ind, ls=ls, align=hdr[2] if hdr[2] <= 7 else 6)
        rep = shapes[0]
        varied = any(x != rep for x in shapes)
        units = b"".join(struct.pack("<H", c) for c, _a in chars) + struct.pack("<H", 13)
        flags = b""
        if varied:
            prev = rep
            parts = []
            for x in shapes:
                if x == prev:
                    parts.append(b"\x01")
                else:
                    parts.append(b"\0" + x)
                    prev = x
            flags = b"".join(parts)
        body.append(b"\0" + struct.pack("<HH", len(chars) + 1, 0) + (b"\x01" if varied else b"\0") + b"\0"
                    + b"\0" * 4 + b"\0" + rep + ps + flags + units)
    body.append(b"\0" + struct.pack("<HH", 0, 0) + b"\0\0" + b"\0" * 4 + b"\0" + _v1_cshape(0, 0, 0))
    return SIGNATURES[0] + data[23:ID_LEN] + bytes(v3info) + b"\0" * SUMMARY_LEN + b"".join(body) + b"\0" * 8


def _upconvert_v1(data: bytes) -> bytes:
    """1.x 문서를 HWP 3.0 바이트로 옮긴다. V1.20 은 글자·문단·쪽 모양까지 옮기고,
    V1.10 은 한글 2024 가 열지 못해 모양의 정답을 확인할 수 없으므로 글과 문단만 기본 모양으로 옮긴다."""
    if data[19:23] == b"1.20":
        return _upconvert_v1_120(data)
    font = struct.pack("<H", 1) + bytes.fromhex("a177b9a1").ljust(40, b"\0")            # 명조
    body = [font * 7, struct.pack("<H", 1), bytes.fromhex("a461c8778b69").ljust(20, b"\0"), _V3_CS, _V3_PS]
    first = True
    for codes in _v1_paras(data):
        units = b"".join(struct.pack("<H", c) for c in codes) + struct.pack("<H", 13)
        body.append((b"\0" if first else b"\x01") + struct.pack("<HH", len(codes) + 1, 0) + b"\0\0" + b"\0" * 4 + b"\0"
                    + _V3_CS + (_V3_PS if first else b"") + units)
        first = False
    body.append(b"\0" + struct.pack("<HH", 0, 0) + b"\0\0" + b"\0" * 4 + b"\0" + _V3_CS)
    return SIGNATURES[0] + data[23:ID_LEN] + _V3_INFO + b"\0" * SUMMARY_LEN + b"".join(body) + b"\0" * 8


def upconvert_v2(path: str) -> bytes:
    """HWP 2.0·2.1 문서를 HWP 3.0 바이트로 올린다(변환 엔진이 3.0 부터 읽기 때문).

    2.1 은 그림 개체(164 → 356 바이트)만 다르고, 2.0 은 여기에 글꼴 언어 5 → 7종, 글자 모양 25 → 31 바이트가 더 있다.
    그 밖의 바이트는 그대로 옮긴다. 압축 문서는 풀어서 압축 없이 쓴다."""
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(V1_PREFIX):
        return _upconvert_v1(data)
    ver, info, body, start = _open_old(data)
    edits: list = []
    blocks, r, st, _p = _walk_old(ver, info, body, edits=edits)
    cut = st.get("cut")
    if ver == 300 and cut is None:
        return data
    if cut is not None and not blocks:
        raise Hwp3Error(f"문서가 첫 문단부터 끊겨 있어 살릴 글이 없습니다({st.get('cut_error')})")
    end = r.p if cut is None else cut
    edits = sorted((e for e in edits if e[0] + e[1] <= end), key=lambda e: e[0])
    out, pos = [], 0
    for p0, n, new in edits:
        if p0 < pos:
            raise Hwp3Error("올림 자리가 겹칩니다")
        out.append(body[pos:p0]); out.append(new); pos = p0 + n
    out.append(body[pos:end])
    if cut is not None:                                # 끊긴 자리에 문단 목록 끝 표지를 붙인다
        out.append(b"\0" + struct.pack("<HH", 0, 0) + b"\0\0" + b"\0" * 4 + b"\0" + b"\0" * CSHAPE)
    head = bytearray(data[:start])
    head[:23] = SIGNATURES[0]
    head[ID_LEN + 124] = 0                             # 압축 없음
    if ver == 200:                                     # 엔진에 원본이 2.0 이었음을 알림(문서 정보 예약 낱말 0x8000)
        head[ID_LEN + 29] |= 0x80
    tail = body[r.p:] if (ver == 300 and cut is None) else b"\0" * 8
    return bytes(head) + b"".join(out) + tail


def salvage_note(path: str):
    """끊기거나 깨진 옛 형식 문서면 (읽힌 문단 블록 수, 까닭) 을, 온전하면 None 을 돌려준다."""
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(V1_PREFIX):
        return None
    ver, info, body, _start = _open_old(data)
    blocks, _r, st, _p = _walk_old(ver, info, body)
    return (len(blocks), st.get("cut_error")) if st.get("cut") is not None else None


def _inflate_all(raw: bytes) -> bytes:
    """압축 문서: 글꼴부터 끝까지가 헤더 없는 deflate. 흐름이 여러 개 이어질 수 있다."""
    out = []
    while raw:
        d = zlib.decompressobj(-15)
        try:
            out.append(d.decompress(raw))
            out.append(d.flush())
        except zlib.error:
            if not out:
                raise Hwp3Error("본문 압축을 풀 수 없습니다")
            break
        if not d.eof:
            break
        if not d.unused_data or len(d.unused_data) == len(raw):
            out.append(d.unused_data or b"")
            break
        raw = d.unused_data
        # 압축 구간 뒤에는 압축하지 않은 꼬리표(미리보기 등)가 온다 — 그대로 붙인다
        out.append(raw)
        break
    return b"".join(out)


def read_hwp3(path: str, autonum_mark: bool = False, visible: bool = False) -> Document:
    from .hwp5 import EncryptedDocument
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(V1_PREFIX):
        blocks = [Paragraph(t) for t in ("".join(hchar(c) for c in codes).strip() for codes in _v1_paras(data)) if t]
        doc = Document(blocks, {"format": "hwp3", "version": data[19:23].decode("ascii", "replace"), "compressed": False,
                                "sections": 1, "preview": "", "title": "", "drawings": 0}, {}, [])
        doc.meta["source"] = os.path.basename(path)
        return doc
    ver, info, body, start = _open_old(data)
    compressed = info[124]
    summary = data[ID_LEN + INFO_LEN:ID_LEN + INFO_LEN + SUMMARY_LEN]
    title = hstr(summary[:112])
    warnings: list = []
    blocks, r, st, p = _walk_old(ver, info, body, autonum_mark, visible)
    if st.get("cut") is not None:
        if not blocks:
            raise Hwp3Error(f"문서가 첫 문단부터 끊겨 있습니다({st.get('cut_error')})")
        warnings.append(f"원본 문서가 중간에 끊겨 있습니다 — 읽힌 데까지만 대조함({st.get('cut_error')})")
    images: dict = {}
    try:                                               # 꼬리표: 1 = 내장 그림(이름 16 + 종류 16 + 자료)
        while ver == 300 and r.p + 8 <= len(r.b):     # 2.x 에는 꼬리표가 없다(문단 목록 뒤 남는 바이트는 읽지 않는다)
            tag, size = r.u32(), r.u32()
            if tag in (0, 0x80000000):
                break
            if size <= 0:
                continue
            if tag == 1 and size >= 32:
                name = r.take(16).split(b"\0", 1)[0].decode("cp949", "replace")
                r.skip(16)
                images["HWP" + name[3:] if len(name) >= 3 else name] = r.take(size - 32)
            else:
                r.skip(size)
    except Hwp3Error:
        warnings.append("내장 그림 꼬리표를 끝까지 읽지 못했습니다")
    meta = {"format": "hwp3", "version": "%d.%02d" % (ver // 100, ver % 100), "compressed": bool(compressed), "sections": 1, "preview": "",
            "title": title, "drawings": st.get("drawings", 0)}
    doc = Document(blocks, meta, images, warnings)
    doc.meta["source"] = os.path.basename(path)
    return doc
