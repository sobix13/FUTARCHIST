// Pure data helper tests, not a browser or DOM interaction test.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync('ownership/static/app.js','utf8');
const escapeLine=source.split('\n').find(line=>line.startsWith('const h='));
const h=vm.runInNewContext(escapeLine+'\nh;');
assert.equal(h('<script>"x" & \'y\'</script>'),'&lt;script&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/script&gt;');
assert.equal(h(null),'');assert.equal(h('Hello'),'Hello');
const displayLine=source.split('\n').find(line=>line.startsWith('function displayValue'));
const display=vm.runInNewContext(escapeLine+'\n'+displayLine+'\ndisplayValue;',{URL});
assert.equal(display('javascript:alert(1)'),'javascript:alert(1)');
assert.equal(display('<img src=x onerror=alert(1)>'),'&lt;img src=x onerror=alert(1)&gt;');
assert.equal(display('https://user:password@example.com'),'https://user:password@example.com');
assert.ok(display('https://example.com/path').includes('rel="noopener noreferrer"'));
assert.equal(display(undefined),'Not provided');
console.log('8 pure JavaScript escaping/link assertions passed. This is not browser UI testing.');
