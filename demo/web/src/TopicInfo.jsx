import { useEffect, useId, useRef } from "react";

const DESCRIPTIONS = {
  "/camera/image_raw":
    "Images captured by the robot’s camera. Monitoring this stream helps identify interrupted or irregular image delivery.",
  "/imu/data":
    "Motion measurements from the inertial sensor, including acceleration and rotation rate, and orientation when available. These help describe how the robot is moving.",
  "/odom":
    "The robot’s estimated position, orientation, and velocity relative to a local reference frame. Useful for tracking motion, though the estimate can drift over time.",
  "/scan":
    "A laser scan measuring distances to surrounding surfaces. Navigation systems use these measurements to detect obstacles and help locate the robot.",
  "/amcl_pose":
    "The robot’s estimated position and orientation within a known map, produced by its localization system. This is an estimate, not ground truth.",
  "/diagnostics":
    "Status reports published by robot components, such as normal operation, warnings, and errors. The details depend on what each component reports.",
  "/_telemetry/gateway_health":
    "Periodic status updates from the telemetry gateway, including buffered messages and delivery state. These help distinguish sensor silence from a telemetry delivery problem.",
  "/_telemetry/gateway_events":
    "Connection and compatibility events observed by the gateway. For example, incompatible message-delivery settings can prevent a topic from being received even while its publisher is running.",
};
const FALLBACK =
  "A named stream of robot messages. No description is available for this topic yet; its contents depend on the publisher and message type.";
export const topicDescription = (topic) => DESCRIPTIONS[topic] || FALLBACK;

export default function TopicInfo({ topic, label }) {
  const id = useId();
  const button = useRef(null);
  const tooltip = useRef(null);
  const timer = useRef(null);
  const cancelClose = () => clearTimeout(timer.current);
  useEffect(() => () => clearTimeout(timer.current), []);

  const show = () => {
    cancelClose();
    const panel = tooltip.current;
    const rect = button.current.getBoundingClientRect();
    panel.showPopover();
    const width = panel.offsetWidth;
    const height = panel.offsetHeight;
    panel.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - width - 12))}px`;
    panel.style.top = `${Math.max(12, rect.bottom + height + 8 <= window.innerHeight ? rect.bottom + 8 : rect.top - height - 8)}px`;
  };
  const closeSoon = () => {
    cancelClose();
    timer.current = setTimeout(() => {
      if (document.activeElement !== button.current)
        tooltip.current?.hidePopover();
    }, 150);
  };

  return (
    <span className="topic-info">
      <button
        ref={button}
        type="button"
        className="topic-info-button"
        aria-label={`About ${label}`}
        aria-describedby={id}
        onMouseEnter={show}
        onMouseLeave={closeSoon}
        onFocus={show}
        onClick={show}
        onBlur={() => tooltip.current?.hidePopover()}
      >
        <span aria-hidden="true">i</span>
      </button>
      <span
        ref={tooltip}
        id={id}
        popover="auto"
        role="tooltip"
        className="topic-tooltip"
        onMouseEnter={cancelClose}
        onMouseLeave={closeSoon}
      >
        {topicDescription(topic)}
      </span>
    </span>
  );
}
