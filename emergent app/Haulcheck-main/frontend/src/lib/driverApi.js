import axios from "axios";

const driverApi = axios.create({ baseURL: `${process.env.REACT_APP_BACKEND_URL}/api` });

driverApi.interceptors.request.use((config) => {
  const token = localStorage.getItem("driver_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export default driverApi;
