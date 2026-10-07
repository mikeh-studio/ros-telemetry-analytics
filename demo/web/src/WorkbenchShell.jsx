import {
  PulseIcon,
  RecordIcon,
  NavigationArrowIcon,
} from "@phosphor-icons/react";

export default function WorkbenchShell({
  activeView,
  setActiveView,
  tabAvailability,
  dialog,
  children,
}) {
  return (
    <main
      className={`workbench-theme ${activeView === "navigation" ? "navigation-workspace" : ""}`}
    >
      <header className="command-header">
        <div className="title-lockup">
          <h1>ROS Workbench</h1>
        </div>
        <span className="workbench-subtitle">Robotics evidence & analysis</span>
      </header>
      {dialog}
      <div
        className="workspace-tabs"
        role="tablist"
        aria-label="ROS Workbench views"
      >
        {[
          ["health", "Telemetry", PulseIcon],
          ["recordings", "Recording", RecordIcon],
          ["localization", "Localization", NavigationArrowIcon],
          ["navigation", "Navigation", NavigationArrowIcon],
        ].map(([id, label, Icon], index) => (
          <button
            key={id}
            id={`view-${id}`}
            role="tab"
            aria-label={label}
            aria-describedby={`availability-${id}`}
            aria-selected={activeView === id}
            aria-controls={`panel-${id}`}
            tabIndex={activeView === id ? 0 : -1}
            onClick={() => setActiveView(id)}
            onKeyDown={(event) => {
              if (
                !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)
              )
                return;
              event.preventDefault();
              const tabs = [
                "health",
                "recordings",
                "localization",
                "navigation",
              ];
              const next =
                event.key === "Home"
                  ? tabs[0]
                  : event.key === "End"
                    ? tabs[tabs.length - 1]
                    : tabs[
                        (index +
                          (event.key === "ArrowRight" ? 1 : tabs.length - 1)) %
                          tabs.length
                      ];
              setActiveView(next);
              document.getElementById(`view-${next}`).focus();
            }}
          >
            <span className="tab-label">
              <Icon
                className="tab-icon"
                size={20}
                weight="regular"
                aria-hidden="true"
                focusable="false"
              />
              {label}
            </span>
            <span className="tab-availability" id={`availability-${id}`}>
              {tabAvailability(id)}
            </span>
          </button>
        ))}
      </div>

      {children}
    </main>
  );
}
