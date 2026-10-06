import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { DigitalCompanion, type CompanionState } from '../src/components/DigitalCompanion';
import '../src/styles.css';

function Harness() {
  const [state, setState] = useState<CompanionState>('idle');
  const [suggestion, setSuggestion] = useState('');
  return <main style={{padding: 24}}>
    <h1>Isolated companion browser regression</h1>
    <nav aria-label="Regression state controls">{(['idle','listening','thinking','speaking','error'] as const).map(value =>
      <button key={value} onClick={() => setState(value)}>{`Fixture ${value}`}</button>)}</nav>
    <DigitalCompanion state={state} subtitle="こんにちは。" emotion="放松" sceneTitle="咖啡店点单"
      sceneImageUrl="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='2' height='2'/%3E"
      suggestions={['おすすめは何ですか？']} onSuggestion={setSuggestion}/>
    <output aria-label="Selected suggestion">{suggestion}</output>
  </main>;
}

createRoot(document.getElementById('root')!).render(<Harness/>);
