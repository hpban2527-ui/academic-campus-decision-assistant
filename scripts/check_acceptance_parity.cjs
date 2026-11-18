// Ensure the offline review UI and Python catalog make identical routing decisions.
const fs=require('fs'),assert=require('assert');
const {assessActivityPolicy}=require('./activity_acceptance.js');
const data=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(const row of data.items)assert.deepStrictEqual(assessActivityPolicy(row,data.acceptance_policy),row.data_policy,'Policy mismatch at #'+row.position);
console.log('PASS: Python/JavaScript policy parity for all '+data.items.length+' records.');
