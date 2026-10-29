/* Declarative editor: no expressions, commands, arbitrary arguments or execution. */
(() => {
  const $ = id => document.getElementById(id);
  let schema, revision, config, override = {};
  async function api(url, body) {
    const response = await fetch(url, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}, body:JSON.stringify(body)});
    const data = await response.json(); if (!response.ok) throw Error(data.error || 'Rule request failed'); return data;
  }
  function error(e) {$('status').textContent = e.message;}
  function node(tag, text) {const element = document.createElement(tag); if (text) element.textContent = text; return element;}
  function button(text, action) {const element = node('button', text); element.type = 'button'; element.onclick = action; return element;}
  function select(values, value, change, multiple = false) {
    const element = node('select'); element.multiple = multiple;
    values.forEach(v => {const option = new Option(v || '(none)', v); option.selected = multiple ? (value || []).includes(v) : value === v; element.append(option);});
    element.onchange = () => change(multiple ? Array.from(element.selectedOptions, o => o.value) : element.value); return element;
  }
  function input(value, change, type = 'text') {const element = node('input'); element.type = type; element.value = value; element.oninput = () => change(type === 'number' ? Number(element.value) : element.value); return element;}
  function label(text, control) {const element = node('label', text + ' '); element.append(control); return element;}
  function actions(container, values) {
    container.replaceChildren();
    ['suggest_trackers','preset','client_profile','requirements'].forEach(key => {
      const multiple = ['suggest_trackers','requirements'].includes(key);
      const options = key === 'requirements' ? config.requirements : config.references[key];
      container.append(label(key, select(multiple ? options : ['', ...options], values[key], value => {
        if (value.length) values[key] = value; else delete values[key];
      }, multiple)));
    });
  }
  function renderOverride() {
    override = JSON.parse(JSON.stringify(schema.overrides[$('candidate').value] || {}));
    actions($('override'), override);
  }
  function render() {
    $('rules').replaceChildren();
    schema.rules.forEach((rule,index) => {
      const section = node('fieldset'); section.append(node('legend','Rule ' + (index + 1)));
      const enabled = node('input'); enabled.type = 'checkbox'; enabled.checked = rule.enabled; enabled.onchange = () => {rule.enabled = enabled.checked;};
      section.append(label('Name', input(rule.name, v => {rule.name = v;})), label('Priority', input(rule.priority, v => {rule.priority = v;}, 'number')), label('Enabled', enabled), label('Match', select(['all','any'], rule.match, v => {rule.match = v;})));
      rule.conditions.forEach((condition, ci) => {
        const row = node('div');
        row.append(label('Field', select(config.fields, condition.field, v => {condition.field = v;})), label('Operator', select(config.operators, condition.operator, v => {condition.operator = v; condition.value = v === 'in' ? [''] : ''; render();})), label('Literal value (IN: comma separated)', input(Array.isArray(condition.value) ? condition.value.join(',') : condition.value, v => {condition.value = condition.operator === 'in' ? v.split(',').map(s => s.trim()) : v;})), button('Remove condition', () => {rule.conditions.splice(ci,1); render();}));
        section.append(row);
      });
      section.append(button('Add condition', () => {rule.conditions.push({field:'category',operator:'equals',value:''}); render();}));
      const actionPanel = node('div'); actions(actionPanel, rule.actions); section.append(actionPanel, button('Remove rule', () => {schema.rules.splice(index,1); render();})); $('rules').append(section);
    });
    renderOverride();
  }
  async function load() {
    config = await api('/api/automation-rules'); schema = config.schema; revision = config.revision;
    const data = await api('/api/automation-rules/candidates'); $('candidate').replaceChildren(); data.candidates.forEach(c => $('candidate').append(new Option(c.label,c.id)));
    render(); $('status').textContent = 'Saved schema loaded. Edits affect suggestions only after explicit confirmation.';
  }
  $('reload').onclick = () => load().catch(error);
  $('add').onclick = () => {if (schema.rules.length >= 32) return error(Error('Maximum 32 rules')); schema.rules.push({name:'Rule ' + (schema.rules.length + 1),priority:0,enabled:true,match:'all',conditions:[{field:'category',operator:'equals',value:'MOVIE'}],actions:{requirements:['screenshot-review']}}); render();};
  $('save').onclick = async () => {try {const data = await api('/api/automation-rules',{schema,revision}); schema = data.schema; revision = data.revision; render(); $('status').textContent = 'Rules saved. No execution or submission was started.';} catch (e) {error(e);}};
  $('candidate').onchange = () => {renderOverride(); $('result').textContent = '';};
  $('set-override').onclick = () => {if (!$('candidate').value || !Object.keys(override).length) return error(Error('Select candidate and at least one action')); schema.overrides[$('candidate').value] = JSON.parse(JSON.stringify(override)); $('status').textContent = 'Draft override set; preview and save to persist.';};
  $('clear-override').onclick = () => {delete schema.overrides[$('candidate').value]; renderOverride();};
  $('preview').onclick = async () => {try {$('result').textContent = JSON.stringify(await api('/api/automation-rules/preview',{id:$('candidate').value,schema}), null, 2);} catch (e) {error(e);}};
  $('import').onchange = async e => {const file = e.target.files[0]; if (!file) return; try {if (file.size > 262144) throw Error('Schema too large'); const imported = JSON.parse(await file.text()); if (!window.confirm('Validate and replace saved rules with this imported schema? This does not execute anything.')) return; const data = await api('/api/automation-rules',{schema:imported,revision}); schema = data.schema; revision = data.revision; render(); $('status').textContent = 'Validated schema imported.';} catch (err) {error(err);}};
  $('export').onclick = async () => {try {const data = await api('/api/automation-rules'); const url = URL.createObjectURL(new Blob([JSON.stringify(data.schema,null,2)],{type:'application/json'})); const link = node('a'); link.href = url; link.download = 'ua-rules-v1.json'; link.click(); URL.revokeObjectURL(url);} catch (e) {error(e);}};
  load().catch(error);
})();
