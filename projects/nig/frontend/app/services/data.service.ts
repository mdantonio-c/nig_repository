import { Injectable } from "@angular/core";
import { HttpClient } from "@angular/common/http";
import { Observable, of } from "rxjs";
import { map, share } from "rxjs/operators";
import { ApiService } from "@rapydo/services/api";
import { Study, Stats } from "@app/types";

@Injectable({
  providedIn: "root",
})
export class DataService {

  constructor(private api: ApiService, private http: HttpClient) {}

  // STUDIES
  getStudies(): Observable<Study[]> {
  	return this.api.get<Study[]>('study');
  }

  getStudy(uuid: string): Observable<Study> {
  	return this.api.get<Study>(`study/${uuid}`);
  }

  getStats(): Observable<Stats> {
    return this.api.get<Stats>('stats/public');
  }
}
