export default function getRemoteFileContent(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('GET', url, true);
    request.responseType = 'blob';
    request.onload = () => {
      if (request.status === 200) {
        const file = new FileReader();
        file.readAsBinaryString(request.response);
        file.onloadend = () => {
          resolve(file.result);
        };
      } else {
        reject(new Error(`Request failed`));
      }
    }
    request.onerror = () => {
      reject(new Error(`Request failed`));
    }
    request.send();
  });
}
