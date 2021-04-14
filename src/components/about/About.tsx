import React from 'react';
import styled, { createGlobalStyle } from 'styled-components';
import icon from '../../assets/img/chia_circle.svg';

const GlobalStyle = createGlobalStyle`
  body,
  html {
    width: 100%;
    height: 100%;
    user-select: none;
    background-color: silver;
  }

  body { 
    margin: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    color: rgb(31, 31, 31);
    background-color: rgb(238, 238, 238);
    font-size: 12px;
    font-family: 'Helvetica', 'Arial', 'ヒラギノ角ゴ Pro W3', 'Hiragino Kaku Gothic Pro', 'メイリオ', Meiryo, 'ＭＳ Ｐゴシック', 'MS PGothic', sans-serif;
  }
`;

const StyledLink = styled.a`
  text-decoration: none;

  &:hover {
    text-decoration: none;
  }
`;

const StyledLogoContainer = styled.div`
  width: 200px;

  img {
    height: 200px;
    margin-bottom: 2rem;
  }
`;

const StyledTitle = styled.h2`
  margin-top: 0;
  margin-bottom: 1rem;
  color: rgb(31, 31, 31);
`;

const StyledSubTitle = styled.h3`
  margin-top: 0;
  margin-bottom: 1rem;
  color: rgb(31, 31, 31);
`;

const BugReport = styled.a`
  position: absolute;
  right: 0.5rem;
  bottom: 0.5rem;
  color: rgb(128, 160, 194);
`;

const VersionsTable = styled.table`
  border-collapse: collapse;
  color: rgb(153, 153, 153);
  font-size: 12px;
`;

const Spacer = styled.div`
  margin-bottom: 1rem;
`;

const url = 'https://chia.net';

type Props = {
  version: string;
  packageJson: {
    productName: string;
    description: string;
  };
  versions: {
    [key: string]: string;
  };
};

export default function About(props: Props) {
  const {
    version,
    packageJson: {
      productName,
      description,
    },
    versions,
  } = props;

  return (
    <html>
      <head>
        <base href="./" />
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, minimum-scale=1.0, initial-scale=1, user-scalable=yes" />
        <title>About {productName}</title>
      </head>
      <body>
        <GlobalStyle />
        <StyledLink href={url}>
          <StyledLogoContainer>
            <img src={icon} />
          </StyledLogoContainer>

          <StyledTitle>{productName} {version}</StyledTitle>
        </StyledLink>
        <StyledSubTitle>{description}</StyledSubTitle>
        <Spacer />
        <div className="copyright">
          Copyright (c) 2021 Chia Network
        </div>
        <Spacer />
        <VersionsTable>
          {versions?.electron && (
            <tr>
              <td>Electron</td>
              <td>{versions?.electron}</td>
            </tr>
          )}
          {versions?.chrome && (
            <tr>
              <td>Chrome</td>
              <td>{versions?.chrome}</td>
            </tr>
          )}
          {versions?.node && (
            <tr>
              <td>Node</td>
              <td>{versions?.node}</td>
            </tr>
          )}
          {versions?.v8 && (
            <tr>
              <td>V8</td>
              <td>{versions?.v8}</td>
            </tr>
          )}
        </VersionsTable>

        <BugReport href="https://github.com/Chia-Network/chia-blockchain/issues" target="_blank">
          Report an issue
        </BugReport>
        {'{{CSS}}'}
      </body>
    </html>
  );
}