import React, { ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

type Props = {
  children?: ReactNode;
  expanded?: boolean;
};

export default function Accordion(props: Props) {
  const { expanded, children } = props;

  return (
    <AnimatePresence>
      {expanded && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

Accordion.defaultProps = {
  children: undefined,
  expanded: false,
};
