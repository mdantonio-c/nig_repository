import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable, of } from "rxjs";
import { map, share } from "rxjs/operators";
import { ApiService } from "@rapydo/services/api";
import { Study } from "@app/types";

@Injectable({
  providedIn: "root",
})
export class DataService {

  constructor(private api: ApiService, private http: HttpClient) {}

  // STUDIES
  // getStudies(): Observable<Study[]> { }
}