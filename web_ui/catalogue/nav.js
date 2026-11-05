(()=>{'use strict';
const groups={overview:['#overview','#capability-note','#summary','.overview-grid'],'queue-section':['#queue-section','#controls-section'],'saved-lists':['#saved-lists'],'media-tools':['#media-tools'],'settings-section':['#settings-section'],'activity-section':['#activity-section']};
const links=[...document.querySelectorAll('.sidebar nav a')];
const queue=document.getElementById('queue-section'),controls=document.getElementById('controls-section');if(queue&&controls)queue.before(controls);
function render(){let key=location.hash.slice(1);if(key==='controls-section')key='queue-section';if(!Object.hasOwn(groups,key))key='overview';for(const [name,selectors]of Object.entries(groups)){for(const selector of selectors){const element=document.querySelector(selector);if(element)element.hidden=name!==key;}}for(const link of links){const active=link.hash==='#'+key;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}}
window.addEventListener('hashchange',render);render();
})();
