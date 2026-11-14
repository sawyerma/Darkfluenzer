export function Messages() {
  // Noch kein Plattform-Adapter im Backend: nur ehrlich als nicht verbunden anzeigen.
  return (
    <section className="g-panel">
      <h1>Nachrichten</h1>
      <div className="g-section">
        <div className="g-line">
          <span>Telegram</span>
          <span className="g-badge">NICHT VERBUNDEN</span>
        </div>
      </div>
    </section>
  );
}
