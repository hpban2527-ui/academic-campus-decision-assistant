/* Offline counterpart of sp1.acceptance; parity-tested against the same 129 records. */
function assessActivityPolicy(row, policy) {
  const record=JSON.parse(JSON.stringify(row.record)), unsure=new Set(row.unsure||[]),soft=new Set(policy.soft_fields);
  const warningFields=[...unsure].filter(f=>soft.has(f)).sort();
  for(const f of warningFields)if(f in record&&!['multi_session','duration_minutes_stated'].includes(f))record[f]=null;
  let reasons=[],warnings=[],schedule=null;
  const source=row.source_text||'',kind=record.post_type,mode=record.mode;
  if(kind!=='activity')reasons.push(kind==='info_only'?'not_an_activity':'insufficient_activity_information');
  if(!record.title)reasons.push('missing_title');
  if(!['online','offline','hybrid'].includes(mode))reasons.push('missing_mode');
  reasons.push(...[...unsure].filter(f=>!soft.has(f)).sort().map(f=>'uncertain:'+f));
  if(record.domain===null)warnings.push('domain_unknown');
  const fee=record.fee;let budgetKnown=typeof fee==='number';
  if(fee===null)warnings.push('fee_unknown','bounded_cost_unknown');
  else if(typeof fee==='object'){budgetKnown=fee.per==='person'&&!fee.deposit;if(!budgetKnown)warnings.push('fee_not_per_person')}
  if(!record.registration_url)warnings.push('registration_link_missing');
  if(!record.registration_deadline)warnings.push('registration_deadline_missing');
  if(['offline','hybrid'].includes(mode)&&!record.location)warnings.push('location_unknown');
  if(record.multi_session)warnings.push('multiple_sessions');
  warnings.push(...warningFields.map(f=>'uncertain_soft:'+f));
  const iso=d=>new Date(d.getTime()+7*3600000).toISOString().slice(0,19)+'+07:00';
  const moment=(s,closing=false)=>{if(s===null||s===undefined)return null;const [y,m,d]=s.slice(0,10).split('-').map(Number),calendar=new Date(Date.UTC(y,m-1,d));if(calendar.getUTCFullYear()!==y||calendar.getUTCMonth()!==m-1||calendar.getUTCDate()!==d)throw Error('invalid calendar date');return new Date(s.includes('T')?s:s+(closing?'T23:59+07:00':'T00:00+07:00'))};
  const start=record.window_open,end=record.window_close;
  try{
    const opening=moment(start);let closing=moment(end,true),minutes=record.duration_minutes_stated;
    if(unsure.has('duration_minutes_stated'))minutes=null;
    const validMinutes=Number.isInteger(minutes)&&minutes>0;
    const quiz=mode==='online'&&new RegExp(policy.quiz_pattern,'i').test(source)&&!new RegExp(policy.live_pattern,'i').test(source);
    if((opening&&!Number.isFinite(opening.getTime()))||(closing&&!Number.isFinite(closing.getTime())))throw Error('invalid time');
    if(!opening)reasons.push('missing_activity_date');
    else if(quiz){
      if(!closing)reasons.push('missing_quiz_window_end');
      else if(closing<=opening)reasons.push('invalid_quiz_window');
      else{
        if(!validMinutes){minutes=policy.default_quiz_duration_minutes;warnings.push('quiz_duration_default')}
        if(closing-opening<minutes*60000)reasons.push('quiz_duration_exceeds_window');
        else schedule={type:'FLEXIBLE_WINDOW',window_start:iso(opening),window_end:iso(closing),duration_minutes:minutes,duration_source:validMinutes?'stated':'team_default',bounds_precision:!start.includes('T')||!end.includes('T')?'date_only':'time'};
      }
    }else if(!start.includes('T'))reasons.push('missing_fixed_start_time');
    else{
      const closeTimed=end!==null&&end!==undefined&&end.includes('T');
      if(end&&!closeTimed&&end.slice(0,10)!==start.slice(0,10))reasons.push('missing_first_session_end_time');
      else if(closeTimed&&closing<=opening)reasons.push('end_before_start');
      else{
        let durationSource='stated_window';
        if(!closeTimed){if(!validMinutes){minutes=policy.default_fixed_duration_minutes[mode];warnings.push('fixed_duration_default')}durationSource=validMinutes?'stated_duration':'team_default';closing=minutes?new Date(opening.getTime()+minutes*60000):null}
        if(closing)schedule={type:'FIXED',start:iso(opening),end:iso(closing),duration_source:durationSource};else reasons.push('missing_duration');
      }
    }
  }catch{reasons.push('invalid_schedule_value')}
  reasons=[...new Set(reasons)];warnings=[...new Set(warnings)];
  if(reasons.length){schedule=null;if(record.mandatory_stated===true)warnings.push('mandatory_unscheduled')}
  const status=kind==='info_only'?'NOT_AN_ACTIVITY':reasons.length?'NOT_SCHEDULABLE':warnings.length?'READY_WITH_WARNINGS':'READY';
  return {policy_version:policy.version,status,ready_for_scheduling:!reasons.length,reasons,warnings,uncertain_fields:[...unsure].sort(),schedule,accepted_record:record,budget_known:budgetKnown,scoring_verified:false,student_eligibility_verified:false,human_approved:row.review?.status==='approved',processing_label:'AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD'};
}
if(typeof module!=='undefined')module.exports={assessActivityPolicy};
