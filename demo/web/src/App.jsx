import DatasetContext, {
  capability,
  AnalysisUnavailable,
} from "./DatasetContext";
import WorkbenchShell from "./WorkbenchShell";
import UploadRecordingDialog from "./UploadRecordingDialog";
import TelemetryView from "./TelemetryView";
import LocalizationInvestigation from "./LocalizationInvestigation";
import LocalizationOverview from "./LocalizationOverview";
import RecordingInvestigation from "./RecordingInvestigation";
import NavigationRegression from "./NavigationRegression";
import useWorkbenchState from "./useWorkbenchState";
import useWorkspaceView from "./useWorkspaceView";
import { API_URL, EMPTY_LOCALIZATION } from "./workbenchConfig";

export default function App() {
  const [activeView, setActiveView] = useWorkspaceView();
  const state = useWorkbenchState();
  const {
    tabAvailability,
    availableDatasets,
    selectedDataset,
    chooseDataset,
    catalogNotice,
    uploading,
    uploadDialog,
    setUploadError,
    datasetLocked,
    snapshot,
    selectedRunMatches,
    selectedDatasetId,
    localization,
    refreshEvidenceCatalog,
  } = state;
  return (
    <WorkbenchShell
      activeView={activeView}
      setActiveView={setActiveView}
      tabAvailability={tabAvailability}
      dialog={
        <UploadRecordingDialog
          dialogRef={uploadDialog}
          uploading={uploading}
          error={state.uploadError}
          onUpload={state.uploadDataset}
        />
      }
    >
      {activeView !== "navigation" && (
        <DatasetContext
          datasets={availableDatasets}
          selected={selectedDataset}
          onSelect={chooseDataset}
          notice={catalogNotice}
          action={
            <button
              className="header-upload"
              disabled={uploading}
              onClick={() => {
                setUploadError("");
                if (uploadDialog.current && !uploadDialog.current.open)
                  uploadDialog.current.showModal();
              }}
            >
              {uploading ? "Uploading…" : "Upload recording"}
            </button>
          }
          onRefresh={() => refreshEvidenceCatalog()}
        />
      )}

      {datasetLocked && (
        <aside className="active-run-banner" role="status">
          Replay {snapshot.run?.payload?.status} on{" "}
          {snapshot.dataset_name || snapshot.dataset_id}.
          {!selectedRunMatches && (
            <>
              <span> Finish this replay before starting another.</span>
              <button
                onClick={() => {
                  chooseDataset(snapshot.dataset_id);
                  setActiveView("health");
                }}
              >
                Return to active replay
              </button>
            </>
          )}
        </aside>
      )}

      <TelemetryView
        state={state}
        activeView={activeView}
        setActiveView={setActiveView}
      />
      <section
        id="panel-localization"
        role="tabpanel"
        aria-labelledby="view-localization"
        hidden={activeView !== "localization"}
      >
        {capability(selectedDataset, "localization") !== "ready" ? (
          <AnalysisUnavailable dataset={selectedDataset} view="localization" />
        ) : (
          <LocalizationInvestigation
            key={selectedDatasetId}
            standalone
            active={activeView === "localization"}
            evaluation={
              localization.dataset_id === selectedDatasetId
                ? localization
                : {
                    ...EMPTY_LOCALIZATION,
                    detail:
                      localization.detail || "Loading selected evaluation…",
                  }
            }
            apiUrl={API_URL}
            overview={
              <LocalizationOverview
                points={
                  localization.dataset_id === selectedDatasetId
                    ? localization.trajectory || []
                    : []
                }
              />
            }
          />
        )}
      </section>
      <section
        id="panel-recordings"
        role="tabpanel"
        aria-labelledby="view-recordings"
        hidden={activeView !== "recordings"}
      >
        {["ready", "limited", "stale", "not_analyzed"].includes(
          capability(selectedDataset, "recordings"),
        ) ? (
          <RecordingInvestigation
            key={selectedDatasetId}
            datasetId={selectedDatasetId}
            apiUrl={API_URL}
            active={activeView === "recordings"}
            onEvidenceRebuilt={refreshEvidenceCatalog}
          />
        ) : (
          <AnalysisUnavailable dataset={selectedDataset} view="recordings" />
        )}
      </section>
      <section
        id="panel-navigation"
        role="tabpanel"
        aria-labelledby="view-navigation"
        hidden={activeView !== "navigation"}
      >
        <NavigationRegression />
      </section>
    </WorkbenchShell>
  );
}
