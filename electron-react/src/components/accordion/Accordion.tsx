import React, { useState, useRef } from "react";
import { Typography } from "@material-ui/core";
import { ChevronRight as ChevronRightIcon } from "@material-ui/icons";
import "./Accordion.css";

type Props = {
  content: string,
};

export default function Accordion(props: Props) {
  const [setActive, setActiveState] = useState("");
  const [setHeight, setHeightState] = useState("0px");
  const [setRotate, setRotateState] = useState("accordion__icon");
  const [setTitle, setTitleState] = useState("View pending balances...");
  const content = useRef<HTMLDivElement>(null);
  function toggleAccordion() {
    setActiveState(setActive === "" ? "active" : "");
    setHeightState(
      setActive === "active" ? "0px" : `${content.current?.scrollHeight}px`
    );
    setRotateState(
      setActive === "active" ? "accordion__icon" : "accordion__icon rotate"
    );
    setTitleState(
      setActive === "active"
        ? "View pending balances..."
        : "Hide pending balances"
    );
  }
  return (
    <div className="accordion__section">
      <Typography
        component="h6"
        variant="subtitle1"
        className={`accordion ${setActive}`}
        onClick={toggleAccordion}
      >
        <ChevronRightIcon className={`${setRotate}`} />
        <p className="accordion_title">{`${setTitle}`}</p>
      </Typography>
      <div
        ref={content}
        style={{ maxHeight: `${setHeight}` }}
        className="accordion__content"
      >
        <div
          className="accordion__text"
          dangerouslySetInnerHTML={{ __html: props.content }}
        />
      </div>
    </div>
  );
}
