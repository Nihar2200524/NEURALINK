"""Bounded DOM-to-Markdown extraction. Web content remains untrusted data."""
from playwright.async_api import Locator

EXTRACT = r"""root => {
 let count=0, size=0;
 const text=s=>s.replace(/\s+/g,' ').trim().replace(/[\\`*_\[\]<>]/g,'\\$&');
 const walk=e=>{
  if(++count>20000) throw Error('EXTRACTION_LIMIT');
  if(e.nodeType===3){size+=e.textContent.length;if(size>2000000)throw Error('EXTRACTION_LIMIT');return text(e.textContent);}
  if(e.nodeType!==1)return '';
  const tag=e.tagName.toLowerCase();
  if(['script','style','noscript','template','iframe'].includes(tag)||e.hidden||e.getAttribute('aria-hidden')==='true')return '';
  if(tag==='input'||tag==='textarea'||tag==='select')return ''; // Never export field values.
  if(tag==='table'){
   const rows=Array.from(e.rows).map(r=>Array.from(r.cells).map(c=>walk(c).replace(/\|/g,'\\|').replace(/\n/g,' ')));
   if(!rows.length)return '';
   const width=Math.max(...rows.map(r=>r.length));
   const row=r=>'| '+Array.from({length:width},(_,i)=>r[i]||'').join(' | ')+' |';
   return '\n\n'+[row(rows[0]),row(Array(width).fill('---')),...rows.slice(1).map(row)].join('\n')+'\n\n';
  }
  const children=Array.from(e.childNodes).map(walk).join(' ');
  if(/^h[1-6]$/.test(tag))return '\n\n'+'#'.repeat(Number(tag[1]))+' '+children.trim()+'\n\n';
  if(tag==='li')return '\n- '+children.trim();
  if(tag==='br')return '\n';
  if(tag==='pre')return '\n\n    '+children.replace(/\n/g,'\n    ')+'\n\n';
  if(tag==='a'){
   const href=e.getAttribute('href')||'';
   if(/^https?:/i.test(href))return '['+children+']('+href.replace(/[()\s]/g,c=>encodeURIComponent(c))+')';
  }
  const result=['p','div','section','article','main','ul','ol','blockquote'].includes(tag)?'\n\n'+children.trim()+'\n\n':children;
  return result+(e.shadowRoot?Array.from(e.shadowRoot.childNodes).map(walk).join(' '):'');
 };
 return walk(root).replace(/\n[ \t]+/g,'\n').replace(/\n{3,}/g,'\n\n').trim();
}"""


async def markdown(locator: Locator) -> str:
    result: str = await locator.evaluate(EXTRACT)
    return result
