import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: JSX.Element;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'Automated Task Execution',
    description: (
      <>
        Automate repetitive tasks to save time and reduce errors. Penguin can execute commands and scripts based on your input.
      </>
    ),
  },
  {
    title: 'Project Structure Creation',
    description: (
      <>
        Quickly set up new projects with predefined structures, including folders and files, to kickstart development.
      </>
    ),
  },
  {
    title: 'Code Writing Assistance',
    description: (
      <>
        Get help writing clean, efficient, and well-documented code. Penguin suggests improvements and best practices.
      </>
    ),
  },
  {
    title: 'Debugging and Explanations',
    description: (
      <>
        Identify and fix bugs with detailed explanations and solutions provided by Penguin.
      </>
    ),
  },
  {
    title: 'Supports LiteLLM, can be run locally',
    description: (
      <>
        Integrates with LiteLLM, allowing support for over 100 different LLM providers, offering flexibility and choice in AI models.
      </>
    ),
  },
];

function Feature({title, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): JSX.Element {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
