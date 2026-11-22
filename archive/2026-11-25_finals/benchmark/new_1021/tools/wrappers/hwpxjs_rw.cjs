// hwpx-js(babpulss) read(.hwp) -> write(.hwpx). 사용: node hwpxjs_rw.cjs <in.hwp> <out.hwpx>
const fs = require('fs'); const path = require('path');
const NM = process.env.BCN_NODE_MODULES || '/dev/shm/bcn/npm/node_modules';
const { read, write } = require(path.join(NM, 'hwpx-js'));
const doc = read(new Uint8Array(fs.readFileSync(process.argv[2])));
fs.writeFileSync(process.argv[3], Buffer.from(write(doc)));
