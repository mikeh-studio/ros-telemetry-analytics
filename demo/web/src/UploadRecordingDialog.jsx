export default function UploadRecordingDialog({
  dialogRef,
  uploading,
  error,
  onUpload,
}) {
  return (
    <dialog
      className="add-data-dialog"
      ref={dialogRef}
      aria-labelledby="add-data-title"
    >
      <div className="add-data-heading">
        <h2 id="add-data-title">Upload recording</h2>
        <button
          className="add-data-button"
          onClick={() => dialogRef.current.close()}
          aria-label="Close upload recording"
        >
          Close
        </button>
      </div>
      <p>Choose a ROS recording to add to your available datasets.</p>
      <label className="upload-control">
        Upload recording
        <input
          type="file"
          accept=".bag,.mcap,.db3"
          disabled={uploading}
          onChange={onUpload}
        />
        <span>
          {uploading ? "Validating upload…" : "Choose .bag, .mcap, or .db3"}
        </span>
      </label>
      <p role="status">
        {uploading
          ? "Uploading and validating your recording…"
          : "After validation, your recording will be selected for replay."}
      </p>
      {error && (
        <p className="upload-error" role="alert">
          {error}
        </p>
      )}
    </dialog>
  );
}
